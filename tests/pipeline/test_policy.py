"""The run cycle as a decision table.

Every guarantee ARCHITECTURE.md claims for the decider core is a case
here: brake before persistence, delivery before commit, exactly one
Finish per path, waiting as a branch. Plain dataclasses in, one Step
out — no mocks, no I/O.
"""

from pathlib import Path

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

SCHOOLS = 8
BRAKE = 0.2


def diff_result(
    new_count=648,
    known_count=170_361,
    files_transformed=8,
    fetch_failures=0,
) -> DiffResult:
    return DiffResult(
        new_count=new_count,
        known_count=known_count,
        files_transformed=files_transformed,
        fetch_failures=fetch_failures,
        diff_path=Path("diff.csv"),
        master_path=Path("master.csv"),
    )


def ready_to_deliver(diff: DiffResult | None = None) -> CycleState:
    """A state that has fetched everything and computed a healthy diff."""
    return (
        CycleState()
        .with_query_submitted()
        .with_staged(SCHOOLS)
        .with_diff(diff if diff is not None else diff_result())
    )


# --- getting to the diff ---


def test_a_fresh_run_submits_queries_first():
    assert decide(CycleState(), SCHOOLS, BRAKE) == SubmitQueries()


def test_partial_staging_before_the_deadline_waits():
    state = CycleState().with_query_submitted().with_staged(3)
    assert decide(state, SCHOOLS, BRAKE) == AwaitStaging()


def test_full_staging_moves_on_to_the_diff():
    state = CycleState().with_query_submitted().with_staged(SCHOOLS)
    assert decide(state, SCHOOLS, BRAKE) == ComputeDiff()


def test_nothing_staged_by_the_deadline_fails_loudly():
    state = (
        CycleState()
        .with_query_submitted()
        .with_staged(0)
        .with_staging_deadline_passed()
    )
    step = decide(state, SCHOOLS, BRAKE)
    assert step == Finish(
        status="failed",
        step="awaiting_results",
        error="NoResultsStaged",
        reason="no results staged by deadline",
    )


def test_partial_staging_past_the_deadline_proceeds():
    # Missing schools are acceptable; the union master means nothing drifts.
    state = (
        CycleState()
        .with_query_submitted()
        .with_staged(5)
        .with_staging_deadline_passed()
    )
    assert decide(state, SCHOOLS, BRAKE) == ComputeDiff()


# --- judging the diff ---


def test_all_downloads_failing_is_a_failure_not_an_empty_success():
    state = ready_to_deliver(
        diff=diff_result(new_count=0, files_transformed=0, fetch_failures=8)
    )
    step = decide(state, SCHOOLS, BRAKE)
    assert isinstance(step, Finish)
    assert step.status == "failed"
    assert step.error == "AllDownloadsFailed"


def test_an_empty_diff_completes_without_delivering():
    state = ready_to_deliver(diff=diff_result(new_count=0))
    assert decide(state, SCHOOLS, BRAKE) == Finish(status="success")


def test_the_brake_fires_before_anything_is_delivered_or_committed():
    state = ready_to_deliver(diff=diff_result(new_count=100_000))
    step = decide(state, SCHOOLS, BRAKE)
    assert isinstance(step, Finish)
    assert step.status == "blocked"
    assert step.error == "SuspiciousDiffVolume"


def test_brake_off_delivers_the_flood():
    state = ready_to_deliver(diff=diff_result(new_count=100_000))
    assert decide(state, SCHOOLS, None) == DeliverDiff(state.diff)


def test_a_first_ever_run_is_exempt_from_the_brake():
    state = ready_to_deliver(diff=diff_result(new_count=4200, known_count=0))
    assert decide(state, SCHOOLS, BRAKE) == DeliverDiff(state.diff)


# --- delivering and committing, in that order ---


def test_a_healthy_diff_is_delivered_before_the_master_moves():
    state = ready_to_deliver()
    assert decide(state, SCHOOLS, BRAKE) == DeliverDiff(state.diff)


def test_the_master_is_committed_only_after_delivery():
    state = ready_to_deliver().with_delivered()
    assert decide(state, SCHOOLS, BRAKE) == CommitMaster(state.diff)


def test_delivered_and_committed_completes():
    state = ready_to_deliver().with_delivered().with_master_committed()
    assert decide(state, SCHOOLS, BRAKE) == Finish(status="success")


def test_losing_the_date_claim_still_commits_then_skips():
    # A crashed prior run may have delivered without committing; redoing
    # the commit is a union, so it is safe either way.
    state = ready_to_deliver().with_delivered_elsewhere()
    assert decide(state, SCHOOLS, BRAKE) == CommitMaster(state.diff)

    committed = state.with_master_committed()
    step = decide(committed, SCHOOLS, BRAKE)
    assert isinstance(step, Finish)
    assert step.status == "skipped"


# --- the shape itself ---


def test_decide_is_pure():
    state = ready_to_deliver()
    assert decide(state, SCHOOLS, BRAKE) == decide(state, SCHOOLS, BRAKE)


def test_every_path_ends_in_exactly_one_terminal_decision():
    """Drive any state forward by simulating perfect executors: whatever
    decide asks for succeeds. Every start state must reach Finish, and
    the step sequence must never repeat a non-waiting step."""
    starts = [
        CycleState(),
        CycleState().with_query_submitted().with_staged(SCHOOLS),
        ready_to_deliver(),
        ready_to_deliver(diff=diff_result(new_count=0)),
        ready_to_deliver().with_delivered(),
        ready_to_deliver().with_delivered_elsewhere(),
    ]
    for state in starts:
        seen = []
        for _ in range(10):
            step = decide(state, SCHOOLS, BRAKE)
            if isinstance(step, Finish):
                break
            assert step not in seen, f"repeated step {step} from {state}"
            seen.append(step)
            if isinstance(step, SubmitQueries):
                state = state.with_query_submitted()
            elif isinstance(step, AwaitStaging):
                state = state.with_staged(SCHOOLS)
            elif isinstance(step, ComputeDiff):
                state = state.with_diff(diff_result())
            elif isinstance(step, DeliverDiff):
                state = state.with_delivered()
            elif isinstance(step, CommitMaster):
                state = state.with_master_committed()
        else:
            raise AssertionError(f"never finished from {state}")
