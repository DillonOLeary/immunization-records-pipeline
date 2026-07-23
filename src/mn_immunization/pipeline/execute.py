"""Executors for the decider core, and the loop that runs them.

`run_to_completion` is the runner: decide, execute the one named step,
fold what it learned back into the state, repeat. It is the only place
terminal events are written — the run ends when and only when `decide`
says `Finish`. Executors are dumb dispatch onto the adapters; every
decision they might have been tempted to make lives in `policy.decide`.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mn_immunization.domain.ic_format import IcFormatError, render_csv
from mn_immunization.gcp.secrets import get_secret
from mn_immunization.ledger import events
from mn_immunization.ledger.gcs_ledger import read_recent_runs, sha256_hex
from mn_immunization.pipeline.files import (
    generate_vaccination_record_filename,
    transformed_filename,
)
from mn_immunization.pipeline.incremental import commit_master, compute_diff
from mn_immunization.pipeline.policy import (
    AwaitStaging,
    CommitMaster,
    ComputeDiff,
    CycleState,
    DeliverDiff,
    DiffResult,
    Finish,
    SubmitQueries,
    decide,
)
from mn_immunization.pipeline.support import append_event, claim_or_proceed
from mn_immunization.sinks.drive import upload_to_google_drive
from mn_immunization.sources.aisr.actions import (
    AISRActionFailedError,
    get_latest_vaccination_records_url,
)
from mn_immunization.sources.aisr.client import AisrClient, aisr_session
from mn_immunization.sources.aisr.parsing import AisrParseError, parse_aisr_csv

if TYPE_CHECKING:
    from mn_immunization.pipeline.cycles import RunContext

logger = logging.getLogger(__name__)

STEP_NAMES = {
    SubmitQueries: "submit_queries",
    AwaitStaging: "awaiting_results",
    ComputeDiff: "compute_diff",
    DeliverDiff: "deliver_diff",
    CommitMaster: "commit_master",
}


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
                logger.error("Bulk query failed for %s: %s", school.school_name, error)
    return failures


def _submit_queries(ctx: RunContext, username: str, password: str) -> None:
    """Period claim, then roster submission. A rerun that loses the claim
    submits nothing: MIIC emails every nurse on each submission."""
    period = datetime.now().strftime(os.environ.get("QUERY_PERIOD_FORMAT", "%Y-%m"))
    if claim_or_proceed(ctx.ledger, f"{period}_query"):
        logger.info("Submitting roster queries for period %s", period)
        failures = submit_roster_queries(ctx, username, password)
        if failures:
            logger.error("%d school(s) failed roster submission", failures)
    else:
        logger.info(
            "Roster queries already submitted for period %s; "
            "skipping submission (rerun-safe, no duplicate email)",
            period,
        )


def _probe_staged(ctx: RunContext, username: str, password: str) -> int:
    with aisr_session(ctx.auth_url, ctx.api_url, username, password) as client:
        staged = staged_school_count(client, ctx.schools)
    logger.info("%d/%d schools have results staged", staged, len(ctx.schools))
    return staged


def _compute_diff(ctx: RunContext, username: str, password: str) -> DiffResult:
    """Fetch staged results, transform, and diff. Reads only: nothing this
    executor does needs unwinding if the brake fires next."""
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
                content = client.download_latest_records(school.school_id, output_path)
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
                logger.error("Download failed for %s: %s", school.school_name, error)

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

    output_files = list(output_folder.glob("*.csv"))
    diff_path, master_path, new_count, known_count = compute_diff(
        output_files=output_files,
        output_folder=output_folder,
        bucket_name=ctx.bucket_name,
        temp_dir=ctx.temp,
        ledger=ctx.ledger,
    )
    logger.info("Created incremental diff file: %s", diff_path.name)
    return DiffResult(
        new_count=new_count,
        known_count=known_count,
        files_transformed=len(output_files),
        fetch_failures=fetch_failures,
        diff_path=diff_path,
        master_path=master_path,
    )


def _delivered_elsewhere(ctx: RunContext, diff_filename: str) -> bool:
    """Did any recent run record a Drive delivery of this diff file?

    Distinguishes "another run delivered" from "a claimant crashed before
    delivering". Errs toward False: zero deliveries is the unacceptable
    failure mode, a duplicate delivery is the old survivable one.
    """
    bucket = getattr(ctx.ledger, "bucket", None)
    if bucket is None:
        return False
    now = datetime.now()
    previous = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    try:
        runs = read_recent_runs(bucket, ((now.year, now.month), previous), limit=20)
    except Exception as error:
        logger.warning(
            "could not read recent runs (%s); assuming not delivered",
            type(error).__name__,
        )
        return False
    return any(
        event["type"] == "Delivered"
        and event["data"].get("target") == "drive"
        and event["data"].get("file_name") == diff_filename
        for run in runs
        for event in run["events"]
    )


def _deliver_diff(ctx: RunContext, diff: DiffResult, folder_id: str) -> str:
    """Drive delivery, gated by the date claim. Returns "delivered" or
    "already_delivered"; an upload failure propagates so the run fails
    loudly with the master untouched."""
    filename = diff.diff_path.name
    # The filename starts with the %Y-%m-%d the diff was computed on; the
    # claim shares that date so a run crossing midnight stays consistent.
    date_str = filename[:10]
    if not claim_or_proceed(ctx.ledger, f"{date_str}_diff"):
        if _delivered_elsewhere(ctx, filename):
            logger.info("Skipping delivery: diff already delivered for %s", date_str)
            return "already_delivered"
        logger.warning(
            "date claim %s_diff already taken but no Delivered event found; "
            "delivering anyway (a claimant that crashed before uploading "
            "must not suppress delivery)",
            date_str,
        )
    drive_file_id = upload_to_drive_with_secrets(
        file_path=str(diff.diff_path), filename=filename, folder_id=folder_id
    )
    append_event(ctx.ledger, events.delivered(filename, "drive", str(drive_file_id)))
    logger.info("Uploaded incremental diff file to Google Drive: %s", filename)
    return "delivered"


def _commit_master(ctx: RunContext, diff: DiffResult) -> None:
    commit_master(
        bucket_name=ctx.bucket_name,
        master_path=diff.master_path,
        ledger=ctx.ledger,
        snapshots=ctx.snapshots,
        # The union master is the known set plus exactly the new records.
        record_count=diff.known_count + diff.new_count,
    )


def _brake_fraction() -> float | None:
    raw = os.environ.get("DIFF_SANITY_FRACTION", "0.2")
    return None if raw == "off" else float(raw)


def _finish(ctx: RunContext, step: Finish, state: CycleState) -> dict:
    """The one place terminal events are written."""
    diff = state.diff
    if step.status == "success":
        files = diff.files_transformed if diff else 0
        new = diff.new_count if diff else 0
        append_event(
            ctx.ledger,
            events.run_completed(
                schools=len(ctx.schools),
                files_transformed=files,
                new_records=new,
                fetch_failures=diff.fetch_failures if diff else 0,
            ),
        )
        logger.info("Cycle completed: %d files, %d new records", files, new)
        return {
            "status": "success",
            "files_transformed": files,
            "new_records": new,
        }
    if step.status == "skipped":
        append_event(ctx.ledger, events.run_skipped(step.reason))
        return {"status": "skipped", "reason": step.reason}
    if step.status == "blocked":
        logger.error("BLOCKED: %s", step.reason)
    append_event(ctx.ledger, events.run_failed(step=step.step, error=step.error))
    return {"status": step.status, "reason": step.reason}


def run_to_completion(
    ctx: RunContext,
    username: str,
    password: str,
    sleep=time.sleep,
    clock=time.monotonic,
) -> dict:
    """Drive the cycle to its terminal event, one decided step at a time.

    A step that raises becomes a loud RunFailed naming the step; nothing
    after it runs, which is what makes "delivery failed" leave the master
    untouched instead of silently absorbing undelivered records.
    """
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not folder_id:
        # Checked before anything happens: a misconfigured delivery target
        # must not cost the period's one roster submission.
        append_event(
            ctx.ledger, events.run_failed(step="delivery", error="NoDriveFolder")
        )
        return {"status": "failed", "reason": "GOOGLE_DRIVE_FOLDER_ID not set"}

    interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "14400"))
    deadline = int(os.environ.get("POLL_DEADLINE_SECONDS", "72000"))
    brake = _brake_fraction()

    state = CycleState()
    start = clock()
    probed = False

    while True:
        step = decide(state, len(ctx.schools), brake)
        if isinstance(step, Finish):
            return _finish(ctx, step, state)

        name = STEP_NAMES[type(step)]
        try:
            if isinstance(step, SubmitQueries):
                _submit_queries(ctx, username, password)
                state = state.with_query_submitted()
            elif isinstance(step, AwaitStaging):
                if probed:
                    remaining = deadline - (clock() - start)
                    if remaining <= 0:
                        state = state.with_staging_deadline_passed()
                        continue
                    sleep(min(interval, remaining))
                state = state.with_staged(_probe_staged(ctx, username, password))
                probed = True
            elif isinstance(step, ComputeDiff):
                state = state.with_diff(_compute_diff(ctx, username, password))
            elif isinstance(step, DeliverDiff):
                outcome = _deliver_diff(ctx, step.diff, folder_id)
                state = (
                    state.with_delivered_elsewhere()
                    if outcome == "already_delivered"
                    else state.with_delivered()
                )
            elif isinstance(step, CommitMaster):
                _commit_master(ctx, step.diff)
                state = state.with_master_committed()
        except Exception as error:
            append_event(
                ctx.ledger,
                events.run_failed(step=name, error=type(error).__name__),
            )
            # Error class only in the terminal log line, same PHI rule as
            # the ledger.
            logger.error("cycle failed at %s: %s", name, type(error).__name__)
            return {
                "status": "failed",
                "reason": f"{type(error).__name__} at {name}",
            }
