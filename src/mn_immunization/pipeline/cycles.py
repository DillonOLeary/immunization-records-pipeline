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
import tempfile
from contextlib import contextmanager
from pathlib import Path

from mn_immunization.domain.ic_format import chunk, render_csv
from mn_immunization.gcp.port import ObjectStore
from mn_immunization.ledger import events
from mn_immunization.pipeline.context import RunContext
from mn_immunization.pipeline.execute import (
    probe_staging,
    query_period,
    record_import_confirmations,
    run_to_completion,
)
from mn_immunization.pipeline.incremental import load_known_records
from mn_immunization.pipeline.services import Services
from mn_immunization.pipeline.support import append_event, new_run_id
from mn_immunization.sources.aisr.port import DistrictInfo, SchoolQueryInformation

logger = logging.getLogger(__name__)


@contextmanager
def pipeline_run(
    kind: str, services: Services, trigger: str, include_query_files: bool = False
):
    """Common cycle scaffolding: the run's ledger, config, schools, temp
    dir, and the guarantee that an escaping exception is recorded as
    RunFailed."""
    ledger = services.new_ledger(new_run_id(kind, services.clock.now()))
    append_event(ledger, events.run_started(kind=kind, trigger=trigger))
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config = json.loads(services.objects.read_text("config/config.json"))
            auth_url, api_url = get_aisr_urls_from_config(config)
            district = get_district_from_config(config)
            schools = create_school_info_list(
                config, services.objects, temp_path, include_query_files
            )
            logger.info(
                "Loaded configuration for %d schools: %s",
                len(schools),
                ", ".join(s.school_name for s in schools),
            )
            yield RunContext(
                settings=services.settings,
                clock=services.clock,
                ledger=ledger,
                snapshots=services.snapshots,
                objects=services.objects,
                drive=services.drive,
                open_source=services.open_source,
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


def create_school_info_list(
    config: dict,
    objects: ObjectStore,
    temp_dir: Path,
    include_query_files: bool = True,
) -> list[SchoolQueryInformation]:
    """Create SchoolQueryInformation objects from configuration, staging
    each school's roster in temp when the cycle will submit it."""
    school_info_list = []

    for school in config["schools"]:
        query_file_path = ""

        if include_query_files:
            query_file = temp_dir / f"{school['name']}_query.csv"
            query_file.write_text(
                objects.read_text(school["bulk_query_file"]), encoding="utf-8"
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


def run_cycle(services: Services, trigger: str = "scheduled") -> dict:
    """The whole pipeline, one execution: decide, execute, repeat.

    Before the cycle, reconcile the Drive import queue: files staff have
    deleted (imported) since last run get an ImportConfirmed event. This
    is best-effort and never blocks the delivery work.
    """
    with pipeline_run("run", services, trigger, include_query_files=True) as ctx:
        record_import_confirmations(ctx)
        return run_to_completion(ctx)


def run_rebaseline_cycle(services: Services, trigger: str = "manual") -> dict:
    """Push the entire known set to Drive as numbered chunk files.

    Recovery tool for sync trouble (missed imports, IC drift): every chunk
    goes to the import queue, staff import them all and delete each as
    done. Safe to run any time because Infinite Campus imports are
    idempotent; re-importing known records changes nothing. Chunk size
    exists only to keep individual IC uploads manageable
    (REBASELINE_CHUNK_RECORDS, default 10000).
    """
    with pipeline_run("rebaseline", services, trigger) as ctx:
        if ctx.drive is None:
            append_event(
                ctx.ledger,
                events.run_failed(step="rebaseline", error="NoDriveFolder"),
            )
            return {"status": "failed", "reason": "GOOGLE_DRIVE_FOLDER_ID not set"}

        known = load_known_records(ctx.objects, ctx.snapshots)
        if not known:
            append_event(
                ctx.ledger,
                events.run_failed(step="rebaseline", error="EmptyMaster"),
            )
            return {"status": "failed", "reason": "known-vaccinations master is empty"}

        pieces = chunk(known, ctx.settings.rebaseline_chunk_records)
        date_str = ctx.local_now().strftime("%Y-%m-%d")

        for index, piece in enumerate(pieces, start=1):
            filename = f"{date_str}_rebaseline_{index:02d}-of-{len(pieces):02d}.csv"
            piece_path = ctx.temp / filename
            piece_path.write_text(render_csv(piece), encoding="utf-8")
            drive_file_id = ctx.drive.upload(piece_path, filename)
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


def run_canary_cycle(services: Services, trigger: str = "scheduled") -> dict:
    """Read-only readiness probe: AISR login plus a staged-results count per
    school, and a full read of the known-vaccinations master, so that an
    unreadable master (MasterMissingError, a malformed row) fails here, a day
    before the run. Moves no PHI and sends no email: the master is read
    in memory, and only counts are logged or recorded."""
    with pipeline_run("canary", services, trigger) as ctx:
        logger.info(
            "District zone %s: roster period %s",
            ctx.settings.time_zone.key,
            query_period(ctx),
        )
        with ctx.open_source(ctx.auth_url, ctx.api_url) as source:
            probe = probe_staging(source, ctx.schools, ctx.clock.now())
        available = probe.staged
        if probe.failed:
            # The run cycle tolerates a failed listing (it retries for
            # hours); the canary exists to notice one, so it fails loudly.
            append_event(
                ctx.ledger,
                events.run_failed(step="canary", error="StagingCheckFailed"),
            )
            logger.error(
                "Canary failed: results listing failed for %d/%d schools",
                probe.failed,
                len(ctx.schools),
            )
            return {
                "status": "failed",
                "reason": f"results listing failed for {probe.failed} school(s)",
            }
        known = load_known_records(ctx.objects, ctx.snapshots)

        append_event(
            ctx.ledger,
            events.run_completed(
                schools_checked=len(ctx.schools),
                records_available=available,
                known_records=len(known),
            ),
        )
        logger.info(
            "Canary passed: login ok, %d/%d schools have records available, "
            "master readable with %d known records",
            available,
            len(ctx.schools),
            len(known),
        )
        return {
            "status": "success",
            "schools_checked": len(ctx.schools),
            "records_available": available,
            "known_records": len(known),
        }
