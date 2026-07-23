"""The run cycle's policy, pure: what has happened, and what happens next.

`decide` is the whole pipeline on one screen. It looks at a `CycleState`
and names the single next `Step`; the runner executes that step, folds
what it learned back into the state with the `with_*` transitions, and
asks again. No I/O, no clock, no environment here — which is what makes
the ordering guarantees checkable as a decision table:

- the sanity brake precedes every step that persists anything;
- `DeliverDiff` precedes `CommitMaster`, so a failed delivery leaves the
  master untouched and the records still in tomorrow's diff;
- `Finish` is the only step that ends a run, so the terminal-event
  guarantee is the loop's shape, not a discipline.

Only three facts need durable memory across executions (query submitted,
diff delivered, master committed); fetching, transforming, and diffing
are read-only and cheap, so a resumed run recomputes them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from mn_immunization.pipeline.support import suspicious_diff


@dataclass(frozen=True)
class DiffResult:
    """What ComputeDiff learned. Counts drive decisions; the paths are
    opaque hand-offs to the deliver and commit executors."""

    new_count: int
    known_count: int
    files_transformed: int
    fetch_failures: int
    diff_path: Path
    master_path: Path


@dataclass(frozen=True)
class CycleState:
    query_submitted: bool = False
    staged: int = 0
    staging_deadline_passed: bool = False
    diff: DiffResult | None = None
    delivered: bool = False
    delivered_elsewhere: bool = False
    master_committed: bool = False

    def with_query_submitted(self) -> CycleState:
        """Rosters submitted this run, or the period claim already held."""
        return replace(self, query_submitted=True)

    def with_staged(self, count: int) -> CycleState:
        return replace(self, staged=count)

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
    """End the run. `status` matches the cycle's return dict ("success",
    "skipped", "blocked", "failed"); the runner maps it to the terminal
    event: success -> RunCompleted, skipped -> RunSkipped, blocked and
    failed -> RunFailed(step, error)."""

    status: str
    step: str = ""
    error: str = ""
    reason: str = ""


Step = SubmitQueries | AwaitStaging | ComputeDiff | DeliverDiff | CommitMaster | Finish


def decide(state: CycleState, school_count: int, brake_fraction: float | None) -> Step:
    """Name the single next step. brake_fraction None disables the brake
    (DIFF_SANITY_FRACTION=off)."""
    if not state.query_submitted:
        return SubmitQueries()

    if state.staged < school_count and not state.staging_deadline_passed:
        return AwaitStaging()

    if state.staged == 0:
        return Finish(
            status="failed",
            step="awaiting_results",
            error="NoResultsStaged",
            reason="no results staged by deadline",
        )
    # Partial staging past the deadline proceeds: missing schools are
    # acceptable (staff chase stragglers by hand) and the union master
    # means nothing drifts.

    if state.diff is None:
        return ComputeDiff()

    diff = state.diff

    if diff.files_transformed == 0 and diff.fetch_failures > 0:
        # Every school's download failed. The old shape reported this as
        # a completed run with zero files; an all-failure is a failure.
        return Finish(
            status="failed",
            step="fetch",
            error="AllDownloadsFailed",
            reason=f"all {diff.fetch_failures} school downloads failed",
        )

    if diff.new_count == 0:
        return Finish(status="success")

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
        return Finish(
            status="skipped",
            reason="diff already delivered today by another run",
        )

    return Finish(status="success")
