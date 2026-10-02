"""The run cycle's policy, pure: what has happened, and what happens next.

`decide` is the whole pipeline on one screen. It looks at a `CycleState`
and names the single next `Step`; the runner executes that step, folds
what it learned back into the state with the `with_*` transitions, and
asks again. No I/O, no clock, no environment here — which is what makes
the ordering guarantees checkable as a decision table. One execution (a
`run` or a `tick`) starts from a fresh state; whatever must outlive it is
in the ledger, so a period spans as many executions as staging takes:

- the sanity brake precedes every step that persists anything;
- `DeliverDiff` precedes `CommitMaster`, so a failed delivery leaves the
  master untouched and the records still in tomorrow's diff;
- `Finish` is the only step that ends a run, so the terminal-event
  guarantee is the loop's shape, not a discipline; `Finish("waiting")`
  ends the execution but not the period.

- a school whose roster may already have gone to MIIC is never
  resubmitted (every submission emails every nurse); if any school is
  stuck that way or failed to submit, the run still delivers what it has
  and then ends failed, so the alert fires.

Only three facts need durable memory across executions (rosters
submitted, diff delivered, master committed); fetching, transforming,
and diffing are read-only and cheap, so a resumed run recomputes them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from mn_immunization.records.model import RecordSet


def suspicious_diff(new_count: int, known_count: int, fraction: float = 0.2) -> bool:
    """A diff far larger than history is a symptom, not a delivery.

    A wiped or mismatched master would diff the entire student body as
    "new" and flood the nurses with duplicates. When the known set is
    non-empty and the diff exceeds max(50, fraction*known), block Drive
    delivery and fail the run loudly instead. A genuine first run (empty
    known set) is never blocked; `load_known_records` makes sure an empty
    known set really is a first run.
    """
    if known_count == 0:
        return False
    return new_count > max(50, int(fraction * known_count))


@dataclass(frozen=True)
class Submission:
    """Where each school's roster stands for this period (school ids).

    `submitted`: a QuerySubmitted event exists for it this period, from
    this run or an earlier one. `stuck`: its claim is held but no event
    exists, so it may or may not have gone out; it is never resubmitted
    automatically (a human checks and clears the claim). `failed`: this
    run's attempt raised, or its claim could not be taken.
    """

    submitted: frozenset[str] = frozenset()
    stuck: frozenset[str] = frozenset()
    failed: frozenset[str] = frozenset()

    @property
    def incomplete(self) -> bool:
        return bool(self.stuck or self.failed)


@dataclass(frozen=True)
class DiffResult:
    """What ComputeDiff learned. Counts drive decisions; the record sets
    are hand-offs to the deliver and commit executors."""

    new_count: int
    known_count: int
    files_transformed: int
    fetch_failures: int  # school files that failed to download OR to parse
    new_records: RecordSet  # what to deliver
    known_after: RecordSet  # the known set grown by this fetch: committed last


@dataclass(frozen=True)
class CycleState:
    submission: Submission | None = None
    staged: int = 0
    probed: bool = False  # this execution has looked at staging
    staging_deadline_passed: bool = False  # set at start, from the period
    probe_error: str = ""  # class of the last failed staging probe, if any
    diff: DiffResult | None = None
    delivered: bool = False
    delivered_elsewhere: bool = False
    master_committed: bool = False

    def with_submission(self, submission: Submission) -> CycleState:
        return replace(self, submission=submission)

    def with_staged(self, count: int) -> CycleState:
        """A probe succeeded: its count replaces the last one, and any
        earlier probe failure is forgotten."""
        return replace(self, staged=count, probed=True, probe_error="")

    def with_probe_error(self, error: str) -> CycleState:
        """A probe failed: the staged count stands, the error is kept so a
        deadline with nothing staged can name it."""
        return replace(self, probed=True, probe_error=error)

    def with_staging_deadline_passed(self) -> CycleState:
        return replace(self, staging_deadline_passed=True)

    def with_diff(self, diff: DiffResult) -> CycleState:
        return replace(self, diff=diff)

    def with_delivered(self) -> CycleState:
        return replace(self, delivered=True)

    def with_delivered_elsewhere(self) -> CycleState:
        """The date's diff claim was lost: another run delivered today."""
        return replace(self, delivered=True, delivered_elsewhere=True)

    def with_master_committed(self) -> CycleState:
        return replace(self, master_committed=True)


@dataclass(frozen=True)
class SubmitQueries:
    pass


@dataclass(frozen=True)
class AwaitStaging:
    pass


@dataclass(frozen=True)
class ComputeDiff:
    pass


@dataclass(frozen=True)
class DeliverDiff:
    diff: DiffResult


@dataclass(frozen=True)
class CommitMaster:
    diff: DiffResult


@dataclass(frozen=True)
class Finish:
    """End the execution. `status` matches the cycle's return dict
    ("success", "skipped", "blocked", "failed", "waiting"); the runner maps
    it to the terminal event: success -> RunCompleted, skipped ->
    RunSkipped, blocked and failed -> RunFailed(step, error), waiting ->
    RunWaiting. Every status but waiting also closes the period."""

    status: str
    step: str = ""
    error: str = ""
    reason: str = ""


Step = SubmitQueries | AwaitStaging | ComputeDiff | DeliverDiff | CommitMaster | Finish


def _settle(submission: Submission, finish: Finish) -> Finish:
    """A run that would otherwise end well still fails if any school is
    stuck or failed to submit: its records reached no one this period,
    and only a failed run makes the alert fire."""
    if not submission.incomplete:
        return finish
    return Finish(
        status="failed",
        step="submit_queries",
        error="QuerySubmissionIncomplete",
        reason=(
            f"{len(submission.stuck)} school(s) stuck on a held claim, "
            f"{len(submission.failed)} failed to submit"
        ),
    )


def decide(state: CycleState, brake_fraction: float | None) -> Step:
    """Name the single next step. brake_fraction None disables the brake
    (DIFF_SANITY_FRACTION=off)."""
    submission = state.submission
    if submission is None:
        return SubmitQueries()

    if not submission.submitted:
        # Nothing went out (now or earlier this period), so nothing will
        # stage: fail now rather than wait 20 hours to learn it.
        return Finish(
            status="failed",
            step="submit_queries",
            error="NoQueriesSubmitted",
            reason=(
                f"no roster submitted this period: {len(submission.stuck)} "
                f"stuck, {len(submission.failed)} failed"
            ),
        )

    # Only the submitted schools can stage; stuck and failed ones are not
    # waited for. Each execution looks once; short of the deadline, a
    # short count ends the execution and the next tick looks again.
    expected = len(submission.submitted)
    if state.staged < expected:
        if not state.probed:
            return AwaitStaging()
        if not state.staging_deadline_passed:
            return Finish(
                status="waiting",
                reason=f"{state.staged}/{expected} schools have results staged",
            )

    if state.staged == 0:
        # If probes were failing at the deadline, that failure is the
        # likelier story than "MDH never staged anything"; name it.
        return Finish(
            status="failed",
            step="awaiting_results",
            error=state.probe_error or "NoResultsStaged",
            reason="no results staged by deadline",
        )
    # Partial staging past the deadline proceeds: missing schools are
    # acceptable (staff chase stragglers by hand) and the union master
    # means nothing drifts.

    if state.diff is None:
        return ComputeDiff()

    diff = state.diff

    if diff.files_transformed == 0 and diff.fetch_failures > 0:
        # Every school's file failed to download or to parse. The old shape
        # reported this as a completed run with zero files; an all-failure
        # is a failure. (A MIIC format change lands here, not in "success".)
        return Finish(
            status="failed",
            step="fetch",
            error="AllDownloadsFailed",
            reason=f"all {diff.fetch_failures} school files failed to fetch",
        )

    if diff.new_count == 0:
        return _settle(submission, Finish(status="success"))

    if brake_fraction is not None and suspicious_diff(
        diff.new_count, diff.known_count, brake_fraction
    ):
        # Before anything has been persisted: nothing to unwind.
        return Finish(
            status="blocked",
            step="diff_sanity",
            error="SuspiciousDiffVolume",
            reason=(
                f"diff of {diff.new_count} records against "
                f"{diff.known_count} known is suspiciously large; "
                "blocking Drive delivery"
            ),
        )

    if not state.delivered:
        return DeliverDiff(diff)

    if not state.master_committed:
        # Reached whether this run delivered or a crashed prior run did:
        # committing is a union, idempotent, so redoing it is safe.
        return CommitMaster(diff)

    if state.delivered_elsewhere:
        return _settle(
            submission,
            Finish(
                status="skipped",
                reason="diff already delivered today by another run",
            ),
        )

    return _settle(submission, Finish(status="success"))
