"""The pipeline's run cycles.

`run_cycle` is the whole pipeline in one execution: submit roster queries,
poll until MDH stages the results, then download, diff, and deliver. One
scheduler triggers it. Claims in the ledger make reruns safe: a rerun
skips the roster submission (so nurses are never emailed twice for one
period) and cannot re-deliver a diff already delivered.

`run_canary_cycle` is a read-only probe (login + staged-results count),
kept for manual readiness checks; it touches no PHI and sends no email.

Each cycle owns its ledger and guarantees a terminal event.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
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
from mn_immunization.sources.aisr.client import AisrClient, aisr_session
from mn_immunization.sources.aisr.parsing import AisrParseError, parse_aisr_csv

logger = logging.getLogger(__name__)

# Master file name in GCS output folder
ALL_KNOWN_VACCINATIONS_FILE = "all_known_vaccinations.csv"


def new_run_id(kind: str) -> str:
    return f"{kind}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def append_event(ledger, event) -> None:
    """Best-effort ledger append: a ledger write failure must not sink a
    delivery."""
    try:
        ledger.append(event)
    except Exception as error:
        logger.warning("ledger append failed for %s: %s", event.type, error)


def claim_or_proceed(ledger, key: str) -> bool:
    """Claim a key; exactly one run can win it. If the claim check itself
    fails (storage outage), proceed: performing an action twice is the old,
    survivable failure mode; performing it zero times is not."""
    try:
        return ledger.claim(key)
    except Exception as error:
        logger.warning(
            "claim check for %s failed (%s); proceeding without guard", key, error
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


def poll_until(
    check: Callable[[], int],
    target: int,
    interval_s: float,
    deadline_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Run check() until it reaches target or the deadline passes.

    Checks immediately, then every interval_s. Returns the last check
    result, which callers compare against target to distinguish success
    from timeout.
    """
    start = clock()
    while True:
        current = check()
        if current >= target:
            return current
        remaining = deadline_s - (clock() - start)
        if remaining <= 0:
            return current
        sleep(min(interval_s, remaining))


@dataclass
class RunContext:
    ledger: GcsRunLedger
    snapshots: GcsSnapshotStore
    bucket_name: str
    temp: Path
    auth_url: str
    api_url: str
    schools: list[SchoolQueryInformation] = field(default_factory=list)


@contextmanager
def pipeline_run(
    kind: str, bucket_name: str, trigger: str, include_query_files: bool = False
):
    """Common cycle scaffolding: ledger, config, schools, temp dir, and the
    guarantee that an escaping exception is recorded as RunFailed."""
    bucket = get_storage_client().bucket(bucket_name)
    ledger = GcsRunLedger(bucket, new_run_id(kind))
    snapshots = GcsSnapshotStore(bucket)
    append_event(ledger, events.run_started(kind=kind, trigger=trigger))
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config = load_config_from_storage(bucket_name, temp_path)
            auth_url, api_url = get_aisr_urls_from_config(config)
            schools = create_school_info_list(
                config, bucket_name, temp_path, include_query_files
            )
            print(
                f"Loaded configuration for {len(schools)} schools: "
                f"{', '.join(s.school_name for s in schools)}"
            )
            yield RunContext(
                ledger=ledger,
                snapshots=snapshots,
                bucket_name=bucket_name,
                temp=temp_path,
                auth_url=auth_url,
                api_url=api_url,
                schools=schools,
            )
    except Exception as error:
        append_event(
            ledger,
            events.run_failed(step=f"{kind}_cycle", error=type(error).__name__),
        )
        raise


def load_config_from_storage(bucket_name: str, temp_dir: Path) -> dict:
    """Load configuration from storage"""
    bucket = get_storage_client().bucket(bucket_name)
    config_file = temp_dir / "config.json"
    bucket.blob("config/config.json").download_to_filename(str(config_file))
    with open(config_file) as f:
        return json.load(f)


def create_school_info_list(
    config: dict, bucket_name: str, temp_dir: Path, include_query_files: bool = True
) -> list[SchoolQueryInformation]:
    """Create SchoolQueryInformation objects from configuration"""
    school_info_list = []

    if include_query_files:
        bucket = get_storage_client().bucket(bucket_name)

    for school in config["schools"]:
        query_file_path = ""

        if include_query_files:
            query_file = temp_dir / f"{school['name']}_query.csv"
            bucket.blob(school["bulk_query_file"]).download_to_filename(
                str(query_file)
            )
            query_file_path = str(query_file)

        school_info_list.append(
            SchoolQueryInformation(
                school_name=school["name"],
                classification=school["classification"],
                school_id=school["id"],
                email_contact=school["email"],
                query_file_path=query_file_path,
            )
        )

    return school_info_list


def get_aisr_credentials() -> tuple[str, str]:
    """Get AISR username and password from secrets"""
    return get_secret("aisr-username"), get_secret("aisr-password")


def get_aisr_urls_from_config(config: dict) -> tuple[str, str]:
    """Get AISR API URLs from configuration"""
    api_config = config["api"]
    return api_config["auth_base_url"], api_config["aisr_api_base_url"]


def staged_school_count(client: AisrClient, schools) -> int:
    """How many schools have results staged, via read-only listing."""
    staged = 0
    for school in schools:
        url = get_latest_vaccination_records_url(
            session=client.session,
            base_url=client.api_base_url,
            access_token=client.access_token,
            school_id=school.school_id,
        )
        if url:
            staged += 1
    return staged


def combine_ic_files(paths: list[Path]) -> RecordSet:
    """Combine IC-format CSV files into one deduplicated RecordSet.

    Files that cannot be parsed are logged and skipped: one bad school
    file must not sink the rest.
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

    Any failure yields an empty set: the pipeline then treats all current
    records as new, which is safe for a first run and — combined with the
    sanity brake — loud instead of harmful otherwise.
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
    The master is the union of everything ever seen: absence is never
    deletion, so a school whose download fails keeps its records and does
    not get re-delivered as "new" when it recovers.
    """
    logger.info("Starting incremental vaccination processing")

    current_records = combine_ic_files(output_files)
    known_records = load_known_records(bucket_name, temp_dir)

    new_records = current_records.diff(known_records)
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

    master_file_path = output_folder / ALL_KNOWN_VACCINATIONS_FILE
    master_text = render_csv(master_records)
    master_file_path.write_text(master_text, encoding="utf-8")
    logger.info("Updated master file with %d total records", len(master_records))

    snapshot_path = ""
    if snapshots is not None:
        try:
            _, snapshot_path = snapshots.put(master_text)
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
        if ledger is not None:
            append_event(ledger, events.delivered(diff_filename, "gcs"))

        master_blob_name = f"output/{ALL_KNOWN_VACCINATIONS_FILE}"
        upload_file_to_storage(bucket_name, master_blob_name, str(master_file_path))
    except Exception as error:
        logger.error("Failed to upload to GCS: %s", error)

    return diff_file_path, master_file_path, len(new_records), len(known_records)


def upload_to_drive_with_secrets(file_path: str, filename: str, folder_id=None):
    """Upload file to Google Drive using secrets from Secret Manager"""
    return upload_to_google_drive(
        file_path=file_path,
        filename=filename,
        refresh_token=get_secret("drive-refresh-token"),
        client_id=get_secret("drive-client-id"),
        client_secret=get_secret("drive-client-secret"),
        folder_id=folder_id,
    )


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
                if school.school_name.replace(" ", "_") in output_file.name:
                    school_name = school.school_name
                    break

            drive_filename = f"{timestamp}_{output_file.name}"
            if not school_name:
                logger.warning(
                    "Could not determine school for %s; uploading to root folder",
                    output_file.name,
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
        except Exception as error:
            logger.warning(
                "Drive upload failed for %s: %s", output_file.name, error
            )


def submit_roster_queries(ctx: RunContext, username: str, password: str) -> int:
    """Submit every school's roster query. Returns the failure count."""
    failures = 0
    with aisr_session(ctx.auth_url, ctx.api_url, username, password) as client:
        for school in ctx.schools:
            try:
                client.submit_roster_query(school)
                query_bytes = Path(school.query_file_path).read_bytes()
                append_event(
                    ctx.ledger,
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
    return failures


def download_and_deliver(ctx: RunContext, username: str, password: str) -> dict:
    """Fetch staged results, transform, diff, and deliver. The diff claim
    and the sanity brake both guard the Drive delivery."""
    input_folder = ctx.temp / "input"
    output_folder = ctx.temp / "output"
    input_folder.mkdir(exist_ok=True)
    output_folder.mkdir(exist_ok=True)

    fetch_failures = 0
    with aisr_session(ctx.auth_url, ctx.api_url, username, password) as client:
        for school in ctx.schools:
            output_path = input_folder / (
                generate_vaccination_record_filename(school.school_name)
            )
            try:
                content = client.download_latest_records(
                    school.school_id, output_path
                )
                append_event(
                    ctx.ledger,
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

    for input_file in input_folder.glob("*.csv"):
        try:
            records = parse_aisr_csv(input_file.read_text(encoding="utf-8"))
            output_file = output_folder / transformed_filename(input_file.name)
            output_file.write_text(render_csv(records), encoding="utf-8")
        except (AisrParseError, IcFormatError, OSError) as error:
            # Error class only: parse messages can quote a PHI field value.
            logger.error(
                "Transform failed for file %s: %s",
                input_file.name,
                type(error).__name__,
            )

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_files = list(output_folder.glob("*.csv"))

    if not output_files:
        logger.warning("No output files generated from downloaded results")
        append_event(
            ctx.ledger,
            events.run_completed(
                schools=len(ctx.schools),
                files_transformed=0,
                new_records=0,
                fetch_failures=fetch_failures,
            ),
        )
        return {"status": "success", "files_transformed": 0}

    if not claim_or_proceed(ctx.ledger, f"{date_str}_diff"):
        # Another run already delivered this date's diff; delivering again
        # would put a duplicate, near-empty file in Drive.
        reason = f"diff already delivered for {date_str}"
        print(f"Skipping delivery: {reason}")
        append_event(ctx.ledger, events.run_skipped(reason))
        return {"status": "skipped", "reason": reason}

    diff_file, _, new_count, known_count = process_incremental_vaccinations(
        output_files=output_files,
        output_folder=output_folder,
        bucket_name=ctx.bucket_name,
        temp_dir=ctx.temp,
        ledger=ctx.ledger,
        snapshots=ctx.snapshots,
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
            ctx.ledger,
            events.run_failed(step="diff_sanity", error="SuspiciousDiffVolume"),
        )
        return {"status": "blocked", "reason": reason}

    upload_files_to_destinations(
        output_files, ctx.bucket_name, timestamp, ctx.schools
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
                ctx.ledger,
                events.delivered(diff_file.name, "drive", str(drive_file_id)),
            )
            print(f"Uploaded incremental diff file to Google Drive: {diff_file.name}")
        except Exception as error:
            logger.warning("Drive upload of diff failed: %s", error)

    append_event(
        ctx.ledger,
        events.run_completed(
            schools=len(ctx.schools),
            files_transformed=len(output_files),
            new_records=new_count,
            fetch_failures=fetch_failures,
        ),
    )
    print(f"Cycle completed: {len(output_files)} files, {new_count} new records")
    return {
        "status": "success",
        "files_transformed": len(output_files),
        "new_records": new_count,
    }


def run_cycle(bucket_name: str, trigger: str = "scheduled") -> dict:
    """The whole pipeline, one execution: query, poll, download, deliver.

    Rerun-safe by construction: the period query claim means a rerun never
    resubmits rosters (MIIC emails every nurse on each submission), and the
    date diff claim means a rerun never re-delivers.
    """
    with pipeline_run("run", bucket_name, trigger, include_query_files=True) as ctx:
        username, password = get_aisr_credentials()

        period = datetime.now().strftime(
            os.environ.get("QUERY_PERIOD_FORMAT", "%Y-%m")
        )
        if claim_or_proceed(ctx.ledger, f"{period}_query"):
            print(f"Submitting roster queries for period {period}")
            failures = submit_roster_queries(ctx, username, password)
            if failures:
                logger.error("%d school(s) failed roster submission", failures)
        else:
            print(
                f"Roster queries already submitted for period {period}; "
                "skipping submission (rerun-safe, no duplicate email)"
            )

        interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "14400"))
        deadline = int(os.environ.get("POLL_DEADLINE_SECONDS", "72000"))

        def check() -> int:
            with aisr_session(
                ctx.auth_url, ctx.api_url, username, password
            ) as client:
                staged = staged_school_count(client, ctx.schools)
            print(f"{staged}/{len(ctx.schools)} schools have results staged")
            return staged

        staged = poll_until(check, len(ctx.schools), interval, deadline)

        if staged == 0:
            append_event(
                ctx.ledger,
                events.run_failed(step="awaiting_results", error="NoResultsStaged"),
            )
            return {"status": "failed", "reason": "no results staged by deadline"}

        if staged < len(ctx.schools):
            # Missing schools are acceptable (staff look up stragglers by
            # hand) and the union master means nothing drifts.
            logger.warning(
                "Proceeding with %d/%d schools staged", staged, len(ctx.schools)
            )

        return download_and_deliver(ctx, username, password)


def run_canary_cycle(bucket_name: str, trigger: str = "scheduled") -> dict:
    """Read-only readiness probe: login plus staged-results count per
    school. Touches no PHI; sends no email."""
    with pipeline_run("canary", bucket_name, trigger) as ctx:
        username, password = get_aisr_credentials()
        with aisr_session(ctx.auth_url, ctx.api_url, username, password) as client:
            available = staged_school_count(client, ctx.schools)

        append_event(
            ctx.ledger,
            events.run_completed(
                schools_checked=len(ctx.schools), records_available=available
            ),
        )
        print(
            f"Canary passed: login ok, {available}/{len(ctx.schools)} "
            "schools have records available"
        )
        return {
            "status": "success",
            "schools_checked": len(ctx.schools),
            "records_available": available,
        }
