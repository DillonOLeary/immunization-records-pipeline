"""The pipeline's run cycles: query, download, canary.

One function per cycle, shared by every entrypoint — the Cloud Run Job, the
legacy Cloud Function handlers, and local CLI runs all execute exactly this
code. Each cycle owns its ledger and guarantees a terminal event.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from mn_immunization.domain.ic_format import (
    IcFormatError,
    parse_ic_csv,
    render_csv,
)
from mn_immunization.domain.records import RecordSet
from mn_immunization.ledger import events
from mn_immunization.ledger.gcs_ledger import (
    GcsRunLedger,
    GcsSnapshotStore,
    sha256_hex,
)
from mn_immunization.runtime.cloud.cloud_storage import (
    download_from_storage,
    get_storage_client,
    upload_file_to_storage,
    upload_to_storage,
)
from mn_immunization.runtime.cloud.google_drive import (
    upload_to_google_drive,
    upload_to_school_folder,
)
from mn_immunization.runtime.cloud.secrets import get_secret
from mn_immunization.runtime.files import (
    generate_vaccination_record_filename,
    transformed_filename,
)
from mn_immunization.sources.aisr.actions import (
    AISRActionFailedError,
    SchoolQueryInformation,
    get_latest_vaccination_records_url,
)
from mn_immunization.sources.aisr.client import aisr_session
from mn_immunization.sources.aisr.parsing import AisrParseError, parse_aisr_csv

logger = logging.getLogger(__name__)

# Master file name in GCS output folder
ALL_KNOWN_VACCINATIONS_FILE = "all_known_vaccinations.csv"


def new_run_id(kind: str) -> str:
    return f"{kind}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def append_event(ledger, event) -> None:
    """Best-effort ledger append.

    Until the phase 5 cutover the ledger observes the pipeline; a ledger
    write failure must not sink a delivery.
    """
    try:
        ledger.append(event)
    except Exception as error:
        logger.warning("ledger append failed for %s: %s", event.type, error)


def claim_diff(ledger, date_str: str) -> bool:
    """Claim today's diff delivery; exactly one run per date can win.

    If the claim check itself fails (storage outage), proceed: delivering
    twice is the old, survivable failure mode; delivering zero times is not.
    """
    try:
        return ledger.claim(f"{date_str}_diff")
    except Exception as error:
        logger.warning(
            "claim check failed (%s); proceeding without idempotency guard", error
        )
        return True


def suspicious_diff(new_count: int, known_count: int, fraction: float = 0.2) -> bool:
    """A diff far larger than history is a symptom, not a delivery.

    A wiped or mismatched master would diff the entire student body as
    "new" and flood the nurses with duplicates. When the known set is
    non-empty and the diff exceeds max(50, fraction*known), block Drive
    delivery and fail the run loudly instead. A genuine first run (empty
    known set) is never blocked.
    """
    if known_count == 0:
        return False
    return new_count > max(50, int(fraction * known_count))


def load_config_from_storage(bucket_name: str, temp_dir: Path) -> dict:
    """Load configuration from storage"""
    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)
    config_blob = bucket.blob("config/config.json")

    config_file = temp_dir / "config.json"
    config_blob.download_to_filename(str(config_file))

    with open(config_file) as f:
        return json.load(f)


def create_school_info_list(
    config: dict, bucket_name: str, temp_dir: Path, include_query_files: bool = True
) -> list[SchoolQueryInformation]:
    """Create SchoolQueryInformation objects from configuration"""
    school_info_list = []

    if include_query_files:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)

    for school in config["schools"]:
        query_file_path = ""

        if include_query_files:
            query_blob = bucket.blob(school["bulk_query_file"])
            query_file = temp_dir / f"{school['name']}_query.csv"
            query_blob.download_to_filename(str(query_file))
            query_file_path = str(query_file)

        school_info = SchoolQueryInformation(
            school_name=school["name"],
            classification=school["classification"],
            school_id=school["id"],
            email_contact=school["email"],
            query_file_path=query_file_path,
        )
        school_info_list.append(school_info)

    return school_info_list


def get_aisr_credentials() -> tuple[str, str]:
    """Get AISR username and password from secrets"""
    return get_secret("aisr-username"), get_secret("aisr-password")


def get_aisr_urls_from_config(config: dict) -> tuple[str, str]:
    """Get AISR API URLs from configuration"""
    api_config = config["api"]
    return api_config["auth_base_url"], api_config["aisr_api_base_url"]


def combine_ic_files(paths: list[Path]) -> RecordSet:
    """Combine IC-format CSV files into one deduplicated RecordSet.

    Files that cannot be parsed are logged and skipped, matching historical
    behavior: one bad school file must not sink the rest.
    """
    combined = RecordSet()
    for file_path in paths:
        try:
            records = parse_ic_csv(Path(file_path).read_text(encoding="utf-8"))
        except (IcFormatError, OSError) as error:
            logger.error("Failed to read %s: %s", file_path, error)
            continue
        combined = combined.union(records)
        logger.info("Added %d records from %s", len(records), Path(file_path).name)

    logger.info(
        "Combined dataset contains %d unique vaccination records", len(combined)
    )
    return combined


def load_known_records(bucket_name: str, temp_dir: Path) -> RecordSet:
    """Load the known-vaccinations master file from GCS.

    Any failure (missing master, unreadable content) yields an empty set:
    the pipeline then treats all current records as new, which is safe for a
    first run and loud enough to notice otherwise.
    """
    master_file_path = temp_dir / ALL_KNOWN_VACCINATIONS_FILE
    blob_name = f"output/{ALL_KNOWN_VACCINATIONS_FILE}"
    try:
        download_from_storage(bucket_name, blob_name, str(master_file_path))
        known = parse_ic_csv(master_file_path.read_text(encoding="utf-8"))
        logger.info("Loaded %d known vaccination records", len(known))
        return known
    except Exception as error:
        logger.info("Master file not found or couldn't be loaded: %s", error)
        logger.info("Starting with empty known vaccinations set")
        return RecordSet()


def process_incremental_vaccinations(
    output_files: list[Path],
    output_folder: Path,
    bucket_name: str,
    temp_dir: Path,
    ledger=None,
    snapshots=None,
) -> tuple[Path, Path, int, int]:
    """Compute the diff against known vaccinations and write both files.

    Returns (diff_file_path, master_file_path, new_count, known_count).
    The diff file holds only records new since the last run; the master
    file becomes the union of everything ever seen, also stored as a
    content-addressed snapshot.
    """
    logger.info("Starting incremental vaccination processing")

    current_records = combine_ic_files(output_files)
    known_records = load_known_records(bucket_name, temp_dir)

    new_records = current_records.diff(known_records)
    # Absence is never deletion: the master is the union of everything ever
    # seen, so a school whose download fails this run keeps its records in
    # the master and does not get re-delivered as "new" when it recovers.
    # (This drift caused real duplicate deliveries under the old
    # master-equals-current behavior.)
    master_records = known_records.union(current_records)
    logger.info(
        "Found %d new vaccination records out of %d total",
        len(new_records),
        len(current_records),
    )

    date_str = datetime.now().strftime("%Y-%m-%d")
    diff_filename = f"{date_str}_new_vaccinations.csv"
    diff_file_path = output_folder / diff_filename
    diff_text = render_csv(new_records)
    diff_file_path.write_text(diff_text, encoding="utf-8")
    logger.info("Saved %d new records to %s", len(new_records), diff_filename)

    master_file_path = output_folder / ALL_KNOWN_VACCINATIONS_FILE
    master_text = render_csv(master_records)
    master_file_path.write_text(master_text, encoding="utf-8")
    logger.info("Updated master file with %d total records", len(master_records))

    snapshot_path = ""
    if snapshots is not None:
        try:
            _, snapshot_path = snapshots.put(master_text)
            logger.info("Stored master snapshot at %s", snapshot_path)
        except Exception as error:
            logger.warning("snapshot store failed: %s", error)

    if ledger is not None:
        append_event(
            ledger,
            events.diff_computed(
                new_count=len(new_records),
                total_count=len(current_records),
                known_hash=sha256_hex(render_csv(known_records)),
                diff_hash=sha256_hex(diff_text),
                snapshot_path=snapshot_path,
            ),
        )

    try:
        diff_blob_name = f"output/changes/{diff_filename}"
        upload_file_to_storage(bucket_name, diff_blob_name, str(diff_file_path))
        logger.info("Uploaded diff file to GCS: %s", diff_blob_name)
        if ledger is not None:
            append_event(ledger, events.delivered(diff_filename, "gcs"))

        master_blob_name = f"output/{ALL_KNOWN_VACCINATIONS_FILE}"
        upload_file_to_storage(bucket_name, master_blob_name, str(master_file_path))
        logger.info("Updated master file in GCS: %s", master_blob_name)
    except Exception as error:
        logger.error("Failed to upload to GCS: %s", error)

    logger.info("Completed incremental vaccination processing")
    return diff_file_path, master_file_path, len(new_records), len(known_records)


def upload_to_drive_with_secrets(file_path: str, filename: str, folder_id=None):
    """Upload file to Google Drive using secrets from Secret Manager"""
    try:
        refresh_token = get_secret("drive-refresh-token")
        client_id = get_secret("drive-client-id")
        client_secret = get_secret("drive-client-secret")

        return upload_to_google_drive(
            file_path=file_path,
            filename=filename,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            folder_id=folder_id,
        )
    except Exception as e:
        print(f"ERROR: Google Drive upload failed for {filename}: {str(e)}")
        raise


def upload_files_to_destinations(
    output_files: list[Path],
    bucket_name: str,
    timestamp: str,
    school_info_list: list[SchoolQueryInformation],
) -> None:
    """Upload transformed files to Cloud Storage and per-school Drive folders."""
    for output_file in output_files:
        blob_name = f"output/{timestamp}_{output_file.name}"
        upload_file_to_storage(bucket_name, blob_name, str(output_file))

        drive_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        if not drive_folder_id:
            continue
        try:
            school_name = None
            for school in school_info_list:
                clean_school_name = school.school_name.replace(" ", "_")
                if clean_school_name in output_file.name:
                    school_name = school.school_name
                    break

            drive_filename = f"{timestamp}_{output_file.name}"
            if not school_name:
                print(
                    f"WARNING: Could not determine school for {output_file.name}, "
                    "uploading to root folder"
                )
                upload_to_drive_with_secrets(
                    str(output_file), drive_filename, drive_folder_id
                )
            else:
                upload_to_school_folder(
                    file_path=str(output_file),
                    filename=drive_filename,
                    school_name=school_name,
                    refresh_token=get_secret("drive-refresh-token"),
                    client_id=get_secret("drive-client-id"),
                    client_secret=get_secret("drive-client-secret"),
                    parent_folder_id=drive_folder_id,
                )
                print(
                    f"Uploaded {output_file.name} to {school_name} folder "
                    "in Google Drive"
                )
        except Exception as e:
            print(f"WARNING: Failed to upload {output_file.name} to Google Drive: {e}")


def store_completion_metadata(bucket_name: str, metadata: dict, filename: str) -> None:
    """Store completion metadata to storage"""
    upload_to_storage(bucket_name, filename, json.dumps(metadata, indent=2))


def run_query_cycle(bucket_name: str, trigger: str = "scheduled") -> dict:
    """Submit bulk roster queries to AISR for every configured school."""
    print("Upload function triggered")

    ledger = GcsRunLedger(
        get_storage_client().bucket(bucket_name), new_run_id("query")
    )
    append_event(ledger, events.run_started(kind="query", trigger=trigger))

    try:
        username, password = get_aisr_credentials()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            config = load_config_from_storage(bucket_name, temp_path)
            auth_url, api_url = get_aisr_urls_from_config(config)

            school_info_list = create_school_info_list(
                config, bucket_name, temp_path, include_query_files=True
            )

            school_names = [school.school_name for school in school_info_list]
            print(
                f"Loaded configuration for {len(school_info_list)} schools: "
                f"{', '.join(school_names)}"
            )

            print("Starting AISR bulk queries")
            failures = 0
            with aisr_session(auth_url, api_url, username, password) as client:
                for school in school_info_list:
                    try:
                        client.submit_roster_query(school)
                        query_bytes = Path(school.query_file_path).read_bytes()
                        append_event(
                            ledger,
                            events.query_submitted(
                                school_id=school.school_id,
                                query_file_hash=sha256_hex(
                                    query_bytes.decode("utf-8", errors="replace")
                                ),
                            ),
                        )
                    except AISRActionFailedError as error:
                        failures += 1
                        logger.error(
                            "Bulk query failed for %s: %s", school.school_name, error
                        )

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            results_data = {
                "upload_time": datetime.now().isoformat(),
                "schools_processed": len(school_info_list),
                "status": "completed",
            }

            results_filename = f"uploads/{timestamp}_bulk_query_results.json"
            store_completion_metadata(bucket_name, results_data, results_filename)

            append_event(
                ledger,
                events.run_completed(
                    schools=len(school_info_list), failures=failures
                ),
            )
            print(f"Upload completed: {len(school_info_list)} schools processed")
            return {"status": "success", "schools_processed": len(school_info_list)}
    except Exception as error:
        append_event(
            ledger,
            events.run_failed(step="query_cycle", error=type(error).__name__),
        )
        raise


def run_download_cycle(bucket_name: str, trigger: str = "scheduled") -> dict:
    """Download, transform, diff, and deliver vaccination records."""
    print("Download function triggered")

    bucket = get_storage_client().bucket(bucket_name)
    ledger = GcsRunLedger(bucket, new_run_id("download"))
    snapshots = GcsSnapshotStore(bucket)
    append_event(ledger, events.run_started(kind="download", trigger=trigger))

    try:
        username, password = get_aisr_credentials()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_folder = temp_path / "input"
            output_folder = temp_path / "output"
            input_folder.mkdir(exist_ok=True)
            output_folder.mkdir(exist_ok=True)

            config = load_config_from_storage(bucket_name, temp_path)
            auth_url, api_url = get_aisr_urls_from_config(config)

            school_info_list = create_school_info_list(
                config, bucket_name, temp_path, include_query_files=False
            )

            school_names = [school.school_name for school in school_info_list]
            print(
                f"Loaded configuration for {len(school_info_list)} schools: "
                f"{', '.join(school_names)}"
            )

            print("Starting AISR vaccination record download")
            fetch_failures = 0
            with aisr_session(auth_url, api_url, username, password) as client:
                for school in school_info_list:
                    output_path = input_folder / (
                        generate_vaccination_record_filename(school.school_name)
                    )
                    try:
                        content = client.download_latest_records(
                            school.school_id, output_path
                        )
                        append_event(
                            ledger,
                            events.records_fetched(
                                school_id=school.school_id,
                                content_hash=sha256_hex(content),
                                byte_size=len(content.encode("utf-8")),
                            ),
                        )
                    except AISRActionFailedError as error:
                        fetch_failures += 1
                        logger.error(
                            "Download failed for %s: %s", school.school_name, error
                        )

            print("Starting ETL transformation")
            for input_file in input_folder.glob("*.csv"):
                try:
                    records = parse_aisr_csv(input_file.read_text(encoding="utf-8"))
                    output_file = output_folder / (
                        transformed_filename(input_file.name)
                    )
                    output_file.write_text(render_csv(records), encoding="utf-8")
                except (AisrParseError, IcFormatError, OSError) as error:
                    # Error class only: parse error messages can quote a
                    # malformed field value, and field values are PHI here.
                    logger.error(
                        "Transform failed for file %s: %s",
                        input_file.name,
                        type(error).__name__,
                    )

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            date_str = datetime.now().strftime("%Y-%m-%d")
            output_files = list(output_folder.glob("*.csv"))
            new_count = 0

            if output_files and not claim_diff(ledger, date_str):
                # Another run already delivered this date's diff. Delivering
                # again would put a second, near-empty file with the same
                # name in Drive: the July 2026 double-run incident.
                reason = f"diff already delivered for {date_str}"
                print(f"Skipping delivery: {reason}")
                append_event(ledger, events.run_skipped(reason))
                return {"status": "skipped", "reason": reason}

            if output_files:
                print(
                    f"Processing {len(output_files)} transformed files "
                    "for incremental updates"
                )

                diff_file, _, new_count, known_count = (
                    process_incremental_vaccinations(
                        output_files=output_files,
                        output_folder=output_folder,
                        bucket_name=bucket_name,
                        temp_dir=temp_path,
                        ledger=ledger,
                        snapshots=snapshots,
                    )
                )

                print(f"Created incremental diff file: {diff_file.name}")

                fraction_env = os.environ.get("DIFF_SANITY_FRACTION", "0.2")
                if fraction_env != "off" and suspicious_diff(
                    new_count, known_count, float(fraction_env)
                ):
                    reason = (
                        f"diff of {new_count} records against {known_count} known "
                        "is suspiciously large; blocking Drive delivery"
                    )
                    print(f"BLOCKED: {reason}")
                    append_event(
                        ledger,
                        events.run_failed(
                            step="diff_sanity", error="SuspiciousDiffVolume"
                        ),
                    )
                    return {"status": "blocked", "reason": reason}

                print(
                    f"Uploading {len(output_files)} full backup files to storage "
                    "and Google Drive"
                )
                upload_files_to_destinations(
                    output_files, bucket_name, timestamp, school_info_list
                )

                drive_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
                if drive_folder_id:
                    try:
                        drive_file_id = upload_to_drive_with_secrets(
                            file_path=str(diff_file),
                            filename=diff_file.name,
                            folder_id=drive_folder_id,
                        )
                        append_event(
                            ledger,
                            events.delivered(
                                diff_file.name, "drive", str(drive_file_id)
                            ),
                        )
                        print(
                            "Uploaded incremental diff file to Google Drive: "
                            f"{diff_file.name}"
                        )
                    except Exception as e:
                        print(
                            f"WARNING: Failed to upload diff file "
                            f"to Google Drive: {e}"
                        )

                print("File processing and uploads completed successfully")
            else:
                print("WARNING: No output files generated from ETL process")

            metadata = {
                "download_time": datetime.now().isoformat(),
                "schools_processed": len(school_info_list),
                "files_transformed": len(output_files),
                "incremental_processing": True,
                "diff_file_created": diff_file.name if output_files else None,
                "status": "completed",
            }
            metadata_filename = f"downloads/{timestamp}_download_metadata.json"
            store_completion_metadata(bucket_name, metadata, metadata_filename)

            append_event(
                ledger,
                events.run_completed(
                    schools=len(school_info_list),
                    files_transformed=len(output_files),
                    new_records=new_count,
                    fetch_failures=fetch_failures,
                ),
            )
            print(
                f"Download and ETL completed: {len(output_files)} files processed"
            )
            return {
                "status": "success",
                "schools_processed": len(school_info_list),
                "files_transformed": len(output_files),
                "incremental_processing": True,
            }
    except Exception as error:
        append_event(
            ledger,
            events.run_failed(step="download_cycle", error=type(error).__name__),
        )
        raise


def run_canary_cycle(bucket_name: str, trigger: str = "scheduled") -> dict:
    """Pre-flight check: log in and list records read-only for each school.

    Scheduled the day before the query run so an AISR change (MIIC has said
    the website may change) alerts with a day of slack instead of failing
    silently mid-run. Downloads nothing; touches no PHI.
    """
    print("Canary triggered")

    ledger = GcsRunLedger(
        get_storage_client().bucket(bucket_name), new_run_id("canary")
    )
    append_event(ledger, events.run_started(kind="canary", trigger=trigger))

    try:
        username, password = get_aisr_credentials()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config = load_config_from_storage(bucket_name, temp_path)
            auth_url, api_url = get_aisr_urls_from_config(config)
            school_info_list = create_school_info_list(
                config, bucket_name, temp_path, include_query_files=False
            )

            available = 0
            with aisr_session(auth_url, api_url, username, password) as client:
                for school in school_info_list:
                    url = get_latest_vaccination_records_url(
                        session=client.session,
                        base_url=client.api_base_url,
                        access_token=client.access_token,
                        school_id=school.school_id,
                    )
                    if url:
                        available += 1

            append_event(
                ledger,
                events.run_completed(
                    schools_checked=len(school_info_list),
                    records_available=available,
                ),
            )
            print(
                f"Canary passed: login ok, {available}/{len(school_info_list)} "
                "schools have records available"
            )
            return {
                "status": "success",
                "schools_checked": len(school_info_list),
                "records_available": available,
            }
    except Exception as error:
        append_event(
            ledger,
            events.run_failed(step="canary_cycle", error=type(error).__name__),
        )
        raise
