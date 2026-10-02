"""The runner: decide, execute the one named step, fold what it learned
back into the state, repeat.

It is the only place terminal events are written: the execution ends
when and only when `decide` says `Finish`, and the period closes with it
unless that Finish is "waiting". The executors (`workflow/steps/`) are dumb
dispatch onto the ports; every decision they might have been tempted to
make lives in `policy.decide`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from mn_immunization.workflow import events
from mn_immunization.workflow.context import RunContext
from mn_immunization.workflow.policy import (
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
from mn_immunization.workflow.ports import RegistryLoginError
from mn_immunization.workflow.steps import delivery, diff, staging, submit
from mn_immunization.workflow.support import append_event

logger = logging.getLogger(__name__)


STEP_NAMES = {
    SubmitQueries: "submit_queries",
    AwaitStaging: "awaiting_results",
    ComputeDiff: "compute_diff",
    DeliverDiff: "deliver_diff",
    CommitMaster: "commit_master",
}


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
    if submission.incomplete or submission.stale:
        detail = {
            "stuck_schools": sorted(submission.stuck),
            "failed_schools": sorted(submission.failed),
            "stale_schools": sorted(submission.stale),
        }
        names = {school.id: school.name for school in ctx.schools}
        labelled = (
            ("stuck", submission.stuck),
            ("failed", submission.failed),
            ("sent with its old roster", submission.stale),
        )
        for label, ids in labelled:
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
    submit=submit.submit_queries,
    probe=staging.probe_staged,
    compute=diff.fetch_and_diff,
    deliver=delivery.deliver_diff,
    commit=diff.commit_known,
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
    if ctx.delivery is None:
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
                except RegistryLoginError:
                    raise  # refused credentials: fail now, not at the deadline
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
