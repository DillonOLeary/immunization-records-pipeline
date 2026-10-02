"""Executors for the decider core, and the loop that runs them.

`run_to_completion` is the runner: decide, execute the one named step,
fold what it learned back into the state, repeat. It is the only place
terminal events are written — the execution ends when and only when
`decide` says `Finish`, and the period closes with it unless that Finish
is "waiting". Executors are dumb dispatch onto the adapters; every
decision they might have been tempted to make lives in `policy.decide`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mn_immunization.domain.hashing import sha256_hex
from mn_immunization.domain.records import RecordSet
from mn_immunization.ledger import events
from mn_immunization.pipeline.context import RunContext
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
from mn_immunization.sources.aisr.port import (
    ImmunizationSource,
    QueryNotSentError,
    SchoolQueryInformation,
)

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


# Allowance for clock skew between our ledger stamps and MDH's upload time.
# Stale results are days old, so ten minutes cannot mistake one for fresh.
FRESHNESS_SKEW = timedelta(minutes=10)


def probe_staging(
    source: ImmunizationSource,
    schools: list[SchoolQueryInformation],
    now: datetime,
    submitted_at: dict[str, datetime] | None = None,
) -> StagingProbe:
    """Read-only listing of every school's results.

    AISR keeps a school's previous results listed for days after a run
    (seen in production 2026-10-01: a rerun's first probe found every
    school "staged" with three-day-old files). So when `submitted_at`
    gives a school's submission time this period, its results count as
    staged only if they were uploaded no earlier than that (less
    FRESHNESS_SKEW); older ones are last period's and the probe keeps
    waiting. Without a submission time (the canary), anything listed
    counts.

    A school whose listing fails is counted in `failed` and logged by
    error class; it never aborts the others.
    """
    now_utc = now.astimezone(UTC)
    staged = failed = 0
    for school in schools:
        try:
            results = source.staged_results(school.school_id)
        except Exception as error:
            failed += 1
            logger.warning(
                "Staging check failed for %s: %s",
                school.school_name,
                type(error).__name__,
            )
            continue
        newest = results.newest_upload_at
        since = (submitted_at or {}).get(school.school_id)
        fresh = since is None or (
            newest is not None and newest >= since - FRESHNESS_SKEW
        )
        logger.info(
            "Results listing for %s: %d entries, newest upload %s, staged=%s",
            school.school_name,
            results.entries,
            f"{(now_utc - newest).days}d ago" if newest else "undated",
            results.available and fresh,
        )
        if results.available and fresh:
            staged += 1
    return StagingProbe(staged=staged, failed=failed)


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
    if ctx.drive is None:
        return

    try:
        # Delivered files carry the district-local date they were made on.
        now = ctx.local_now().replace(tzinfo=None)
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
        present = ctx.drive.list_filenames()
    except Exception as error:
        logger.warning("import-confirmation check skipped (%s)", type(error).__name__)
        return

    reminder_days = ctx.settings.import_reminder_days
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


def query_period(ctx: RunContext) -> str:
    """The period this execution works on: one roster submission per
    school per period."""
    return ctx.period


def submitted_this_period(runs: list[dict], period: str) -> set[str]:
    """School ids with a QuerySubmitted event for `period`. Events written
    before per-school claims carry no period and are ignored."""
    return {
        event["data"]["school_id"]
        for run in runs
        for event in run["events"]
        if event["type"] == "QuerySubmitted" and event["data"].get("period") == period
    }


def _submit_queries(ctx: RunContext) -> Submission:
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
    - an upload that raises is `failed`; if it failed before anything was
      uploaded (QueryNotSentError), its claim is released so a rerun can
      submit it, since MIIC received nothing;
    - a roster that cannot be read from the bucket is `failed` before
      anything is claimed.

    Ledger reads happen before anything is claimed, and login before any
    claim too, so a read error or a failed login leaves no claims behind.
    """
    period = query_period(ctx)
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
    with ctx.open_source(ctx.auth_url, ctx.api_url) as source:
        for school in pending:
            try:
                school = _stage_roster(ctx, school)
            except Exception as error:
                failed.add(school.school_id)
                logger.error(
                    "Roster for %s could not be read (%s); not submitting",
                    school.school_name,
                    type(error).__name__,
                )
                continue
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
                source.submit_roster_query(school, ctx.district)
            except Exception as error:
                failed.add(school.school_id)
                logger.error(
                    "Bulk query failed for %s: %s (HTTP %s)",
                    school.school_name,
                    type(error).__name__,
                    getattr(error, "status_code", None),
                )
                if isinstance(error, QueryNotSentError):
                    _release_unsent(ctx, key, school.school_name)
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


def _stage_roster(
    ctx: RunContext, school: SchoolQueryInformation
) -> SchoolQueryInformation:
    """Copy the school's roster from the bucket into this execution's temp
    dir, under the name MDH signing has always been sent as `filePath`."""
    path = ctx.temp / f"{school.school_name}_query.csv"
    roster = ctx.objects.read_text(ctx.roster_paths[school.school_id])
    path.write_text(roster, encoding="utf-8")
    return replace(school, query_file_path=str(path))


def _release_unsent(ctx: RunContext, key: str, school_name: str) -> None:
    """The upload never began, so MIIC emailed no one: give the claim back
    and a rerun submits the school. If the release itself fails, the
    claim stays held and the school shows as stuck, which is safe."""
    try:
        ctx.ledger.release(key)
    except Exception as error:
        logger.warning(
            "Could not release the claim for %s (%s); it will show as stuck",
            school_name,
            type(error).__name__,
        )
        return
    logger.info(
        "Roster for %s was never sent; claim released, a rerun will submit it",
        school_name,
    )


def submission_times(runs: list[dict], period: str) -> dict[str, datetime]:
    """When each school's roster went out for `period` (UTC), from its
    QuerySubmitted event."""
    times: dict[str, datetime] = {}
    for run in runs:
        for event in run["events"]:
            if (
                event["type"] == "QuerySubmitted"
                and event["data"].get("period") == period
            ):
                at = datetime.fromisoformat(event["at"]).replace(tzinfo=UTC)
                school_id = event["data"]["school_id"]
                times[school_id] = max(at, times.get(school_id, at))
    return times


def _probe_staged(ctx: RunContext, school_ids: frozenset[str]) -> int:
    """Staged count among the schools submitted this period, counting only
    results uploaded since each school's submission; the others are not
    waited for."""
    schools = [school for school in ctx.schools if school.school_id in school_ids]
    since = submission_times(ctx.ledger.recent_runs(), query_period(ctx))
    with ctx.open_source(ctx.auth_url, ctx.api_url) as source:
        probe = probe_staging(source, schools, ctx.clock.now(), since)
    logger.info("%d/%d schools have results staged", probe.staged, len(schools))
    return probe.staged


def _compute_diff(ctx: RunContext) -> DiffResult:
    """Fetch every school's latest results and diff them against the known
    set. Reads only: nothing this executor does needs unwinding if the
    brake fires next."""
    current = RecordSet()
    fetched = fetch_failures = 0
    with ctx.open_source(ctx.auth_url, ctx.api_url) as source:
        for school in ctx.schools:
            try:
                result = source.fetch_latest_records(school.school_id)
            except Exception as error:
                # Not listed, not downloadable, or not parseable: one
                # school's loss (after retries) is counted, never fatal to
                # the others. All of them failing is AllDownloadsFailed,
                # which is where a MIIC format change lands.
                fetch_failures += 1
                logger.error(
                    "Fetch failed for %s: %s (HTTP %s)",
                    school.school_name,
                    type(error).__name__,
                    getattr(error, "status_code", None),
                )
                continue
            fetched += 1
            append_event(
                ctx.ledger,
                events.records_fetched(
                    school_id=school.school_id,
                    content_hash=result.content_hash,
                    byte_size=result.byte_size,
                ),
            )
            current = current.union(result.records)
            logger.info(
                "Fetched %d records for %s", len(result.records), school.school_name
            )

    diff_path, master_path, new_count, known_count = compute_diff(
        current=current,
        output_folder=ctx.temp,
        objects=ctx.objects,
        snapshots=ctx.snapshots,
        ledger=ctx.ledger,
        now=ctx.local_now(),
    )
    logger.info("Created incremental diff file: %s", diff_path.name)
    return DiffResult(
        new_count=new_count,
        known_count=known_count,
        files_transformed=fetched,
        fetch_failures=fetch_failures,
        diff_path=diff_path,
        master_path=master_path,
    )


def _drive_deliveries(ctx: RunContext) -> dict[str, str]:
    """Recent Drive deliveries: file name -> content hash ("" for ones
    recorded before hashes were). Empty if the ledger cannot be read,
    which errs toward delivering: zero deliveries is the unacceptable
    failure, a duplicate the survivable one."""
    try:
        runs = ctx.ledger.recent_runs(limit=50)
    except Exception as error:
        logger.warning(
            "could not read recent runs (%s); assuming not delivered",
            type(error).__name__,
        )
        return {}
    return {
        event["data"]["file_name"]: event["data"].get("content_hash", "")
        for run in runs
        for event in run["events"]
        if event["type"] == "Delivered" and event["data"].get("target") == "drive"
    }


def _unused_name(name: str, deliveries: dict[str, str]) -> str:
    """`name`, or `<stem>_2.csv`, `_3`, ... when a different diff already
    went out under it (a second run the same day with new records): every
    delivery gets its own file, and none masks another."""
    stem, suffix = name.rsplit(".", 1)
    candidate, n = name, 2
    while candidate in deliveries:
        candidate, n = f"{stem}_{n}.{suffix}", n + 1
    return candidate


def _deliver_diff(ctx: RunContext, diff: DiffResult) -> str:
    """Drive delivery, at most once per diff *content*. Returns "delivered"
    or "already_delivered"; an upload failure propagates so the run fails
    loudly with the master untouched.

    The claim is the date plus the diff's hash: two runs with the same
    diff (a crash between delivery and commit, then a rerun) race for one
    claim and deliver once; two runs the same day with different diffs
    (new records arrived in between) both deliver. Keying on the date
    alone made the second one look "already delivered", and its records
    would have been committed to the master without ever reaching staff.
    """
    if ctx.drive is None:
        raise RuntimeError("no Drive folder configured")
    digest = sha256_hex(diff.diff_path.read_text(encoding="utf-8"))
    # The filename starts with the %Y-%m-%d the diff was computed on; the
    # claim shares that date so a run crossing midnight stays consistent.
    date_str = diff.diff_path.name[:10]
    won = claim_or_proceed(ctx.ledger, f"{date_str}_diff_{digest[:16]}")
    deliveries = _drive_deliveries(ctx)
    if not won:
        if digest in deliveries.values():
            logger.info("Skipping delivery: this diff was already delivered")
            return "already_delivered"
        logger.warning(
            "diff claim for %s already taken but no delivery of this content "
            "found; delivering anyway (a claimant that crashed before "
            "uploading must not suppress delivery)",
            date_str,
        )
    name = _unused_name(diff.diff_path.name, deliveries)
    drive_file_id = ctx.drive.upload(diff.diff_path, name)
    append_event(
        ctx.ledger,
        events.delivered(name, "drive", str(drive_file_id), content_hash=digest),
    )
    logger.info("Uploaded incremental diff file to Google Drive: %s", name)
    return "delivered"


def _commit_master(ctx: RunContext, diff: DiffResult) -> None:
    commit_master(
        objects=ctx.objects,
        master_path=diff.master_path,
        ledger=ctx.ledger,
        snapshots=ctx.snapshots,
        # The union master is the known set plus exactly the new records.
        record_count=diff.known_count + diff.new_count,
    )


def _finish(ctx: RunContext, step: Finish, state: CycleState) -> dict:
    """The one place terminal events are written. Every outcome but
    "waiting" closes the period first, so the terminal event stays last."""
    diff = state.diff
    submission = state.submission or Submission()
    if step.status == "waiting":
        append_event(ctx.ledger, events.run_waiting(step.reason))
        logger.info("Period %s waiting: %s", ctx.period, step.reason)
        return {"status": "waiting", "reason": step.reason}
    append_event(ctx.ledger, events.period_closed(ctx.period, step.status))
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


@dataclass(frozen=True)
class Executors:
    """The I/O behind each Step. Production runs REAL_EXECUTORS; the loop
    tests pass stubs, so the loop is tested without touching an adapter
    and without monkeypatching."""

    submit: Callable[[RunContext], Submission]
    probe: Callable[[RunContext, frozenset[str]], int]
    compute: Callable[[RunContext], DiffResult]
    deliver: Callable[[RunContext, DiffResult], str]
    commit: Callable[[RunContext, DiffResult], None]


REAL_EXECUTORS = Executors(
    submit=_submit_queries,
    probe=_probe_staged,
    compute=_compute_diff,
    deliver=_deliver_diff,
    commit=_commit_master,
)


def run_to_completion(ctx: RunContext, executors: Executors = REAL_EXECUTORS) -> dict:
    """Advance the execution's period as far as it can go now, one decided
    step at a time, and write the terminal event.

    Waiting for staging never sleeps: a short count ends the execution as
    "waiting" and the next tick looks again, until POLL_DEADLINE_SECONDS
    after the period opened. A step that raises becomes a loud RunFailed
    naming the step and closes the period; nothing after it runs, which is
    what makes "delivery failed" leave the master untouched instead of
    silently absorbing undelivered records.
    """
    if ctx.drive is None:
        # Checked before anything happens: a misconfigured delivery target
        # must not cost the period's one roster submission.
        append_event(ctx.ledger, events.period_closed(ctx.period, "failed"))
        append_event(
            ctx.ledger, events.run_failed(step="delivery", error="NoDriveFolder")
        )
        return {"status": "failed", "reason": "GOOGLE_DRIVE_FOLDER_ID not set"}

    brake = ctx.settings.brake_fraction
    waited = (ctx.clock.now() - ctx.opened_at).total_seconds()
    state = CycleState(
        staging_deadline_passed=waited >= ctx.settings.poll_deadline_seconds
    )

    while True:
        step = decide(state, brake)
        if isinstance(step, Finish):
            return _finish(ctx, step, state)

        name = STEP_NAMES[type(step)]
        try:
            if isinstance(step, SubmitQueries):
                state = state.with_submission(executors.submit(ctx))
            elif isinstance(step, AwaitStaging):
                # decide only probes once a submission exists
                submission = state.submission or Submission()
                try:
                    staged = executors.probe(ctx, submission.submitted)
                except Exception as error:
                    # One AISR blip (a failed login, a maintenance page)
                    # must not end the period's wait. Remember why, and
                    # let the next tick (or the deadline) decide.
                    logger.warning(
                        "Staging probe failed (%s); the next tick retries",
                        type(error).__name__,
                    )
                    state = state.with_probe_error(type(error).__name__)
                else:
                    state = state.with_staged(staged)
            elif isinstance(step, ComputeDiff):
                state = state.with_diff(executors.compute(ctx))
            elif isinstance(step, DeliverDiff):
                outcome = executors.deliver(ctx, step.diff)
                state = (
                    state.with_delivered_elsewhere()
                    if outcome == "already_delivered"
                    else state.with_delivered()
                )
            elif isinstance(step, CommitMaster):
                executors.commit(ctx, step.diff)
                state = state.with_master_committed()
        except Exception as error:
            append_event(ctx.ledger, events.period_closed(ctx.period, "failed"))
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
