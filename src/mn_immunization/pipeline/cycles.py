"""The pipeline's use-cases.

`run_cycle` is the whole pipeline in one execution: `policy.decide`
names each next step (submit queries, await staging, compute the diff,
deliver, commit the master) and `execute.run_to_completion` runs them
until the decision is `Finish`. One scheduler triggers it. Claims in
the ledger make reruns safe: a rerun skips the roster submission (so
nurses are never emailed twice for one period) and never re-delivers a
diff another run already delivered. Delivery precedes the master
commit, so a failed delivery fails loudly with the master untouched.

`run_canary_cycle` is a read-only probe (login + staged-results count).
`run_rebaseline_cycle` pushes the entire known set to Drive in chunks to
recover from sync trouble; safe because IC imports are idempotent.

Each cycle owns its ledger and guarantees a terminal event.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mn_immunization.domain.ic_format import chunk, render_csv
from mn_immunization.gcp.secrets import get_secret
from mn_immunization.gcp.storage import get_storage_client
from mn_immunization.ledger import events
from mn_immunization.ledger.gcs_ledger import GcsRunLedger, GcsSnapshotStore
from mn_immunization.ledger.port import RunLedger, SnapshotStore
from mn_immunization.pipeline.execute import (
    record_import_confirmations,
    run_to_completion,
    staged_school_count,
    upload_to_drive_with_secrets,
)
from mn_immunization.pipeline.incremental import load_known_records
from mn_immunization.pipeline.support import append_event, new_run_id
from mn_immunization.sources.aisr.actions import DistrictInfo, SchoolQueryInformation
from mn_immunization.sources.aisr.client import aisr_session

logger = logging.getLogger(__name__)


@dataclass
class RunContext:
    # Typed to the ports, not the GCS classes: tests pass the in-memory
    # implementations, and the ledger is the declared seam.
    ledger: RunLedger
    snapshots: SnapshotStore
    bucket_name: str
    temp: Path
    auth_url: str
    api_url: str
    district: DistrictInfo
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
            district = get_district_from_config(config)
            schools = create_school_info_list(
                config, bucket_name, temp_path, include_query_files
            )
            logger.info(
                "Loaded configuration for %d schools: %s",
                len(schools),
                ", ".join(s.school_name for s in schools),
            )
            yield RunContext(
                ledger=ledger,
                snapshots=snapshots,
                bucket_name=bucket_name,
                temp=temp_path,
                auth_url=auth_url,
                api_url=api_url,
                district=district,
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
            bucket.blob(school["bulk_query_file"]).download_to_filename(str(query_file))
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


def get_district_from_config(config: dict) -> DistrictInfo:
    """Read the district's AISR upload identity from config.

    No code fallback on purpose: the values were hardcoded to ISD 197
    once, and a missing key must fail loudly rather than silently upload
    under the wrong district.
    """
    return DistrictInfo(
        iddis=config["district"]["iddis"],
        s3_upload_host=config["api"]["s3_upload_host"],
    )


def run_cycle(bucket_name: str, trigger: str = "scheduled") -> dict:
    """The whole pipeline, one execution: decide, execute, repeat.

    Before the cycle, reconcile the Drive import queue: files staff have
    deleted (imported) since last run get an ImportConfirmed event. This
    is best-effort and never blocks the delivery work.
    """
    with pipeline_run("run", bucket_name, trigger, include_query_files=True) as ctx:
        record_import_confirmations(ctx)
        username, password = get_aisr_credentials()
        return run_to_completion(ctx, username, password)


def run_rebaseline_cycle(bucket_name: str, trigger: str = "manual") -> dict:
    """Push the entire known set to Drive as numbered chunk files.

    Recovery tool for sync trouble (missed imports, IC drift): every chunk
    goes to the import queue, staff import them all and delete each as
    done. Safe to run any time because Infinite Campus imports are
    idempotent; re-importing known records changes nothing. Chunk size
    exists only to keep individual IC uploads manageable
    (REBASELINE_CHUNK_RECORDS, default 10000).
    """
    with pipeline_run("rebaseline", bucket_name, trigger) as ctx:
        drive_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        if not drive_folder_id:
            append_event(
                ctx.ledger,
                events.run_failed(step="rebaseline", error="NoDriveFolder"),
            )
            return {"status": "failed", "reason": "GOOGLE_DRIVE_FOLDER_ID not set"}

        known = load_known_records(ctx.bucket_name, ctx.temp)
        if not known:
            append_event(
                ctx.ledger,
                events.run_failed(step="rebaseline", error="EmptyMaster"),
            )
            return {"status": "failed", "reason": "known-vaccinations master is empty"}

        max_records = int(os.environ.get("REBASELINE_CHUNK_RECORDS", "10000"))
        pieces = chunk(known, max_records)
        date_str = datetime.now().strftime("%Y-%m-%d")

        for index, piece in enumerate(pieces, start=1):
            filename = f"{date_str}_rebaseline_{index:02d}-of-{len(pieces):02d}.csv"
            piece_path = ctx.temp / filename
            piece_path.write_text(render_csv(piece), encoding="utf-8")
            drive_file_id = upload_to_drive_with_secrets(
                str(piece_path), filename, drive_folder_id
            )
            append_event(
                ctx.ledger,
                events.delivered(filename, "drive", str(drive_file_id)),
            )
            logger.info("Pushed %s (%d records)", filename, len(piece))

        append_event(
            ctx.ledger,
            events.run_completed(chunks=len(pieces), records=len(known)),
        )
        logger.info(
            "Rebaseline complete: %d records in %d files", len(known), len(pieces)
        )
        return {"status": "success", "chunks": len(pieces), "records": len(known)}


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
        logger.info(
            "Canary passed: login ok, %d/%d schools have records available",
            available,
            len(ctx.schools),
        )
        return {
            "status": "success",
            "schools_checked": len(ctx.schools),
            "records_available": available,
        }
