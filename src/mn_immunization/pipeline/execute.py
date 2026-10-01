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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mn_immunization.domain.ic_format import IcFormatError, render_csv
from mn_immunization.gcp.secrets import get_secret
from mn_immunization.ledger import events
from mn_immunization.ledger.gcs_ledger import sha256_hex
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
    Submission,
    SubmitQueries,
    decide,
)
from mn_immunization.pipeline.support import append_event, claim_or_proceed
from mn_immunization.sinks.drive import list_drive_filenames, upload_to_google_drive
from mn_immunization.sources.aisr.actions import SchoolQueryInformation
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


@dataclass(frozen=True)
class StagingProbe:
    staged: int  # schools whose latest listed entry has a results file
    failed: int  # schools whose listing call failed


def probe_staging(
    client: AisrClient, schools: list[SchoolQueryInformation]
) -> StagingProbe:
    """Read-only listing of every school's results.

    A school whose listing fails is counted in `failed` and logged by
    error class; it never aborts the others. Each school's listing shape
    is logged too (entry count, age of the newest upload; no PHI) to learn
    whether AISR keeps old results between runs. If it does, "any result
    listed" is not "staged for this period", which matters before any move
    to a weekly cadence.
    """
    now = datetime.now(UTC)
    staged = failed = 0
    for school in schools:
        try:
            results = client.staged_results(school.school_id)
        except Exception as error:
            failed += 1
            logger.warning(
                "Staging check failed for %s: %s",
                school.school_name,
                type(error).__name__,
            )
            continue
        newest = results.newest_upload_at
        logger.info(
            "Results listing for %s: %d entries, newest upload %s, staged=%s",
            school.school_name,
            results.entries,
            f"{(now - newest).days}d ago" if newest else "undated",
            results.available,
        )
        if results.available:
            staged += 1
    return StagingProbe(staged=staged, failed=failed)


def upload_to_drive_with_secrets(file_path: str, filename: str, folder_id: str) -> str:
    """Upload file to Google Drive using secrets from Secret Manager"""
    return upload_to_google_drive(
        file_path=file_path,
        filename=filename,
        refresh_token=get_secret("drive-refresh-token"),
        client_id=get_secret("drive-client-id"),
        client_secret=get_secret("drive-client-secret"),
        folder_id=folder_id,
    )


def list_drive_filenames_with_secrets(folder_id: str) -> set[str]:
    """List the pipeline's own files in the Drive folder, via Secret Manager."""
    return list_drive_filenames(
        refresh_token=get_secret("drive-refresh-token"),
        client_id=get_secret("drive-client-id"),
        client_secret=get_secret("drive-client-secret"),
        folder_id=folder_id,
    )


def _days_since_prefix_date(filename: str, now: datetime) -> int | None:
    """Delivered files are named `YYYY-MM-DD_...`; return the age in days,
    or None if the prefix is not a date."""
    try:
        delivered = datetime.strptime(filename[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return (now - delivered).days


def record_import_confirmations(ctx: RunContext) -> None:
    """Notice which delivered files staff have imported and record it.

    The Drive protocol is delete-as-ack: a delivered file that is gone
    from the folder was imported into Infinite Campus. This lists the
    folder, and for each Delivered file not already ImportConfirmed:
    absent -> append ImportConfirmed; still present past
    IMPORT_REMINDER_DAYS -> a warning (true absence alerting waits for a
    weekly cadence, per alerts.tf).

    Entirely best-effort: any failure is logged and swallowed, because a
    confirmation check must never sink a delivery run.
    """
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not folder_id:
        return

    try:
        now = datetime.now()
        runs = ctx.ledger.recent_runs(limit=50)

        delivered: set[str] = set()
        confirmed: set[str] = set()
        for run in runs:
            for event in run["events"]:
                data = event["data"]
                if event["type"] == "Delivered" and data.get("target") == "drive":
                    delivered.add(data["file_name"])
                elif event["type"] == "ImportConfirmed":
                    confirmed.add(data["file_name"])

        outstanding = delivered - confirmed
        if not outstanding:
            return
        present = list_drive_filenames_with_secrets(folder_id)
    except Exception as error:
        logger.warning("import-confirmation check skipped (%s)", type(error).__name__)
        return

    reminder_days = int(os.environ.get("IMPORT_REMINDER_DAYS", "7"))
    for filename in sorted(outstanding):
        if filename not in present:
            append_event(
                ctx.ledger, events.import_confirmed(filename, "deleted from Drive")
            )
            logger.info("Import confirmed (deleted from Drive): %s", filename)
        else:
            age = _days_since_prefix_date(filename, now)
            if age is not None and age >= reminder_days:
                logger.warning(
                    "Delivered file still awaiting import after %d days: %s",
                    age,
                    filename,
                )


def query_period() -> str:
    """The roster-submission period key (QUERY_PERIOD_FORMAT, monthly by
    default): one submission per school per period."""
    return datetime.now().strftime(os.environ.get("QUERY_PERIOD_FORMAT", "%Y-%m"))


def submitted_this_period(runs: list[dict], period: str) -> set[str]:
    """School ids with a QuerySubmitted event for `period`. Events written
    before per-school claims carry no period and are ignored."""
    return {
        event["data"]["school_id"]
        for run in runs
        for event in run["events"]
        if event["type"] == "QuerySubmitted" and event["data"].get("period") == period
    }


def _submit_queries(ctx: RunContext, username: str, password: str) -> Submission:
    """Submit each school's roster at most once per period. Fails closed.

    Every submission makes MIIC email every nurse in the district, so a
    roster that may already have gone out is never sent again:

    - a school with a QuerySubmitted event this period is done;
    - otherwise its per-school claim `<period>_query_<school_id>` is taken
      just before its upload; a lost claim with no event means an earlier
      run may have uploaded and then failed to record it, so the school is
      `stuck`: skipped, and the run will fail loudly for a human to check;
    - a claim that cannot even be checked is `failed`, with nothing sent
      (this is the one claim that fails closed: here, acting twice is the
      failure that matters);
    - an upload that raises is `failed`.

    Ledger reads happen before anything is claimed, and login before any
    claim too, so a read error or a failed login leaves no claims behind.
    """
    period = query_period()
    prefix = f"{period}_query"
    runs = ctx.ledger.recent_runs()
    held = ctx.ledger.held_claims(prefix)
    all_ids = {school.school_id for school in ctx.schools}

    if prefix in held:
        # The period-wide claim from before per-school claims: the whole
        # period's rosters went out under it.
        logger.info("Period %s was submitted under the legacy claim", period)
        return Submission(submitted=frozenset(all_ids))

    submitted = submitted_this_period(runs, period) & all_ids
    pending = [school for school in ctx.schools if school.school_id not in submitted]
    if not pending:
        logger.info(
            "All rosters already submitted for period %s; nothing to send", period
        )
        return Submission(submitted=frozenset(submitted))

    stuck: set[str] = set()
    failed: set[str] = set()
    logger.info("Submitting %d roster(s) for period %s", len(pending), period)
    with aisr_session(ctx.auth_url, ctx.api_url, username, password) as client:
        for school in pending:
            key = f"{prefix}_{school.school_id}"
            try:
                won = ctx.ledger.claim(key)
            except Exception as error:
                failed.add(school.school_id)
                logger.error(
                    "Claim check failed for %s (%s); not submitting",
                    school.school_name,
                    type(error).__name__,
                )
                continue
            if not won:
                stuck.add(school.school_id)
                logger.error(
                    "Roster for %s is claimed but not recorded as submitted "
                    "this period; skipping it (see ONBOARDING: stuck claims)",
                    school.school_name,
                )
                continue
            try:
                client.submit_roster_query(school, ctx.district)
            except Exception as error:
                failed.add(school.school_id)
                logger.error(
                    "Bulk query failed for %s: %s (HTTP %s)",
                    school.school_name,
                    type(error).__name__,
                    getattr(error, "status_code", None),
                )
                continue
            submitted.add(school.school_id)
            query_text = Path(school.query_file_path).read_text(
                encoding="utf-8", errors="replace"
            )
            append_event(
                ctx.ledger,
                events.query_submitted(
                    school_id=school.school_id,
                    query_file_hash=sha256_hex(query_text),
                    period=period,
                ),
            )
    return Submission(
        submitted=frozenset(submitted),
        stuck=frozenset(stuck),
        failed=frozenset(failed),
    )


def _probe_staged(
    ctx: RunContext, username: str, password: str, school_ids: frozenset[str]
) -> int:
    """Staged count among the schools submitted this period; the others
    are not waited for."""
    schools = [school for school in ctx.schools if school.school_id in school_ids]
    with aisr_session(ctx.auth_url, ctx.api_url, username, password) as client:
        probe = probe_staging(client, schools)
    logger.info("%d/%d schools have results staged", probe.staged, len(schools))
    return probe.staged


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
            except Exception as error:
                # One school's failure (after retries) is counted, never
                # fatal to the others; all failing is AllDownloadsFailed.
                fetch_failures += 1
                logger.error(
                    "Download failed for %s: %s (HTTP %s)",
                    school.school_name,
                    type(error).__name__,
                    getattr(error, "status_code", None),
                )

    output_files, transform_failures = transform_downloads(
        sorted(input_folder.glob("*.csv")), output_folder
    )
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
        # A file that downloaded but cannot be parsed is as lost as one that
        # never downloaded: if MIIC changes its format, every school lands
        # here, and that must read as AllDownloadsFailed, not as an empty
        # "success".
        fetch_failures=fetch_failures + transform_failures,
        diff_path=diff_path,
        master_path=master_path,
    )


def transform_downloads(
    input_files: list[Path], output_folder: Path
) -> tuple[list[Path], int]:
    """Turn raw AISR downloads into IC-format files.

    Returns (the IC files written, how many inputs failed). A failure is
    logged by file name and error class only: parse errors describe a
    line and a field, never its value, but the class is all an operator
    needs and the rule is simplest stated absolutely.
    """
    written: list[Path] = []
    failures = 0
    for input_file in input_files:
        try:
            records = parse_aisr_csv(input_file.read_text(encoding="utf-8"))
            output_file = output_folder / transformed_filename(input_file.name)
            output_file.write_text(render_csv(records), encoding="utf-8")
        except (AisrParseError, IcFormatError, OSError) as error:
            failures += 1
            logger.error(
                "Transform failed for file %s: %s",
                input_file.name,
                type(error).__name__,
            )
            continue
        written.append(output_file)
    return written, failures


def _delivered_elsewhere(ctx: RunContext, diff_filename: str) -> bool:
    """Did any recent run record a Drive delivery of this diff file?

    Distinguishes "another run delivered" from "a claimant crashed before
    delivering". Errs toward False: zero deliveries is the unacceptable
    failure mode, a duplicate delivery is the old survivable one.
    """
    try:
        runs = ctx.ledger.recent_runs(limit=20)
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
    submission = state.submission or Submission()
    if step.status == "success":
        files = diff.files_transformed if diff else 0
        new = diff.new_count if diff else 0
        append_event(
            ctx.ledger,
            events.run_completed(
                schools=len(ctx.schools),
                queries_submitted=len(submission.submitted),
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

    # School ids (not PHI) so the operator knows exactly which rosters
    # need a human: stuck ones need a claim checked and cleared.
    detail = {}
    if submission.incomplete:
        detail = {
            "stuck_schools": sorted(submission.stuck),
            "failed_schools": sorted(submission.failed),
        }
        names = {school.school_id: school.school_name for school in ctx.schools}
        for label, ids in (("stuck", submission.stuck), ("failed", submission.failed)):
            for school_id in sorted(ids):
                logger.error(
                    "Roster %s this period: %s (%s)",
                    label,
                    names.get(school_id, school_id),
                    school_id,
                )
    append_event(
        ctx.ledger, events.run_failed(step=step.step, error=step.error, **detail)
    )
    return {"status": step.status, "reason": step.reason, **detail}


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
        step = decide(state, brake)
        if isinstance(step, Finish):
            return _finish(ctx, step, state)

        name = STEP_NAMES[type(step)]
        try:
            if isinstance(step, SubmitQueries):
                state = state.with_submission(_submit_queries(ctx, username, password))
            elif isinstance(step, AwaitStaging):
                if probed:
                    remaining = deadline - (clock() - start)
                    if remaining <= 0:
                        state = state.with_staging_deadline_passed()
                        continue
                    sleep(min(interval, remaining))
                probed = True
                # decide only waits once a submission exists
                submission = state.submission or Submission()
                try:
                    staged = _probe_staged(
                        ctx, username, password, submission.submitted
                    )
                except Exception as error:
                    # One AISR blip (a failed login, a maintenance page)
                    # must not end a 20-hour wait. Keep the last count,
                    # remember why, and let the deadline decide.
                    logger.warning(
                        "Staging probe failed (%s); retrying next interval",
                        type(error).__name__,
                    )
                    state = state.with_probe_error(type(error).__name__)
                else:
                    state = state.with_staged(staged)
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
