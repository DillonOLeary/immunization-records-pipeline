"""The run cycle as a decision table.

Every guarantee ARCHITECTURE.md claims for the decider is a case
here: brake before persistence, delivery before commit, exactly one
Finish per path, waiting as a branch. Plain dataclasses in, one Step
out — no mocks, no I/O.
"""

import pytest

from mn_immunization.records.model import RecordSet
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

SCHOOLS = 8
BRAKE = 0.2
SCHOOL_IDS = frozenset(str(2540 + i) for i in range(SCHOOLS))
ALL_SUBMITTED = Submission(submitted=SCHOOL_IDS)
ONE_STUCK = Submission(submitted=SCHOOL_IDS - {"2540"}, stuck=frozenset({"2540"}))
ONE_FAILED = Submission(submitted=SCHOOL_IDS - {"2541"}, failed=frozenset({"2541"}))


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
        new_records=RecordSet(),
        known_after=RecordSet(),
    )


def ready_to_deliver(diff: DiffResult | None = None) -> CycleState:
    """A state that has fetched everything and computed a healthy diff."""
    return (
        CycleState()
        .with_submission(ALL_SUBMITTED)
        .with_staged(SCHOOLS)
        .with_diff(diff if diff is not None else diff_result())
    )


# --- getting to the diff ---


def test_a_fresh_run_submits_queries_first():
    assert decide(CycleState(), BRAKE) == SubmitQueries()


def test_each_execution_probes_staging_once_submitted():
    state = CycleState().with_submission(ALL_SUBMITTED)
    assert decide(state, BRAKE) == AwaitStaging()


def test_a_short_count_before_the_deadline_ends_the_execution_waiting():
    # Not a failure and not a sleep: the period stays open for the next
    # tick.
    state = CycleState().with_submission(ALL_SUBMITTED).with_staged(3)
    assert decide(state, BRAKE) == Finish(
        status="waiting", reason="3/8 schools have results staged"
    )


def test_a_failed_probe_before_the_deadline_waits_too():
    state = CycleState().with_submission(ALL_SUBMITTED).with_probe_error("Timeout")
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert step.status == "waiting"


def test_past_the_deadline_staging_is_still_probed_once():
    state = CycleState(staging_deadline_passed=True).with_submission(ALL_SUBMITTED)
    assert decide(state, BRAKE) == AwaitStaging()


def test_nothing_staged_with_failing_probes_names_the_probe_error():
    state = (
        CycleState()
        .with_submission(ALL_SUBMITTED)
        .with_probe_error("ConnectionError")
        .with_staging_deadline_passed()
    )
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert (step.status, step.error) == ("failed", "ConnectionError")


def test_a_successful_probe_clears_an_earlier_probe_error():
    state = (
        CycleState().with_submission(ALL_SUBMITTED).with_probe_error("ConnectionError")
    )
    assert state.with_staged(3).probe_error == ""


def test_full_staging_moves_on_to_the_diff():
    state = CycleState().with_submission(ALL_SUBMITTED).with_staged(SCHOOLS)
    assert decide(state, BRAKE) == ComputeDiff()


def test_nothing_staged_by_the_deadline_fails_loudly():
    state = (
        CycleState()
        .with_submission(ALL_SUBMITTED)
        .with_staged(0)
        .with_staging_deadline_passed()
    )
    step = decide(state, BRAKE)
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
        .with_submission(ALL_SUBMITTED)
        .with_staged(5)
        .with_staging_deadline_passed()
    )
    assert decide(state, BRAKE) == ComputeDiff()


# --- roster submission: never twice, and never quietly incomplete ---


def test_nothing_submitted_fails_at_once_without_waiting():
    # Every school stuck or failed: nothing can stage, so waiting 20 hours
    # to learn that would only delay the alert.
    state = CycleState().with_submission(
        Submission(stuck=frozenset({"2540"}), failed=SCHOOL_IDS - {"2540"})
    )
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert (step.status, step.step, step.error) == (
        "failed",
        "submit_queries",
        "NoQueriesSubmitted",
    )


def test_staging_waits_only_for_the_submitted_schools():
    state = CycleState().with_submission(ONE_STUCK).with_staged(SCHOOLS - 1)
    assert decide(state, BRAKE) == ComputeDiff()


def test_a_stuck_school_still_delivers_and_commits_the_rest():
    state = ready_to_deliver().with_submission(ONE_STUCK)
    assert decide(state, BRAKE) == DeliverDiff(state.diff)
    delivered = state.with_delivered()
    assert decide(delivered, BRAKE) == CommitMaster(state.diff)


def test_a_stuck_school_turns_success_into_a_loud_failure():
    state = (
        ready_to_deliver()
        .with_submission(ONE_STUCK)
        .with_delivered()
        .with_master_committed()
    )
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert (step.status, step.error) == ("failed", "QuerySubmissionIncomplete")


def test_a_failed_school_with_an_empty_diff_still_fails():
    state = ready_to_deliver(diff=diff_result(new_count=0)).with_submission(ONE_FAILED)
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert (step.status, step.error) == ("failed", "QuerySubmissionIncomplete")


def test_a_stuck_school_turns_a_skip_into_a_failure():
    state = (
        ready_to_deliver()
        .with_submission(ONE_STUCK)
        .with_delivered_elsewhere()
        .with_master_committed()
    )
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert step.status == "failed"


def test_the_brake_outranks_an_incomplete_submission():
    state = ready_to_deliver(diff=diff_result(new_count=100_000)).with_submission(
        ONE_STUCK
    )
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert (step.status, step.error) == ("blocked", "SuspiciousDiffVolume")


# --- judging the diff ---


def test_all_downloads_failing_is_a_failure_not_an_empty_success():
    state = ready_to_deliver(
        diff=diff_result(new_count=0, files_transformed=0, fetch_failures=8)
    )
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert step.status == "failed"
    assert step.error == "AllDownloadsFailed"


def test_an_empty_diff_completes_without_delivering():
    state = ready_to_deliver(diff=diff_result(new_count=0))
    assert decide(state, BRAKE) == Finish(status="success")


def test_the_brake_fires_before_anything_is_delivered_or_committed():
    state = ready_to_deliver(diff=diff_result(new_count=100_000))
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert step.status == "blocked"
    assert step.error == "SuspiciousDiffVolume"


def test_brake_off_delivers_the_flood():
    state = ready_to_deliver(diff=diff_result(new_count=100_000))
    assert decide(state, None) == DeliverDiff(state.diff)


def test_a_first_ever_run_is_exempt_from_the_brake():
    state = ready_to_deliver(diff=diff_result(new_count=4200, known_count=0))
    assert decide(state, BRAKE) == DeliverDiff(state.diff)


# --- delivering and committing, in that order ---


def test_a_healthy_diff_is_delivered_before_the_master_moves():
    state = ready_to_deliver()
    assert decide(state, BRAKE) == DeliverDiff(state.diff)


def test_the_master_is_committed_only_after_delivery():
    state = ready_to_deliver().with_delivered()
    assert decide(state, BRAKE) == CommitMaster(state.diff)


def test_delivered_and_committed_completes():
    state = ready_to_deliver().with_delivered().with_master_committed()
    assert decide(state, BRAKE) == Finish(status="success")


def test_losing_the_date_claim_still_commits_then_skips():
    # A crashed prior run may have delivered without committing; redoing
    # the commit is a union, so it is safe either way.
    state = ready_to_deliver().with_delivered_elsewhere()
    assert decide(state, BRAKE) == CommitMaster(state.diff)

    committed = state.with_master_committed()
    step = decide(committed, BRAKE)
    assert isinstance(step, Finish)
    assert step.status == "skipped"


# --- the shape itself ---


def test_decide_is_pure():
    state = ready_to_deliver()
    assert decide(state, BRAKE) == decide(state, BRAKE)


@pytest.mark.parametrize(
    "submission", [ALL_SUBMITTED, ONE_STUCK, ONE_FAILED], ids=["all", "stuck", "failed"]
)
def test_every_path_ends_in_exactly_one_terminal_decision(submission):
    """Drive any state forward by simulating perfect executors: whatever
    decide asks for succeeds, and submission comes out as given. Every
    start state must reach Finish without repeating a non-waiting step,
    and an incomplete submission must never finish as success or skip."""
    starts = [
        CycleState(),
        CycleState().with_submission(ALL_SUBMITTED).with_staged(SCHOOLS),
        ready_to_deliver(),
        ready_to_deliver(diff=diff_result(new_count=0)),
        ready_to_deliver().with_delivered(),
        ready_to_deliver().with_delivered_elsewhere(),
    ]
    starts = [
        s if s.submission is None else s.with_submission(submission) for s in starts
    ]
    for state in starts:
        seen = []
        for _ in range(10):
            step = decide(state, BRAKE)
            if isinstance(step, Finish):
                break
            assert step not in seen, f"repeated step {step} from {state}"
            seen.append(step)
            if isinstance(step, SubmitQueries):
                state = state.with_submission(submission)
            elif isinstance(step, AwaitStaging):
                state = state.with_staged(len(submission.submitted))
            elif isinstance(step, ComputeDiff):
                state = state.with_diff(diff_result())
            elif isinstance(step, DeliverDiff):
                state = state.with_delivered()
            elif isinstance(step, CommitMaster):
                state = state.with_master_committed()
        else:
            raise AssertionError(f"never finished from {state}")
        if submission.incomplete:
            assert step.status not in ("success", "skipped"), state


# --- rosters sent stale because the export from IC failed ---

ONE_STALE = Submission(submitted=SCHOOL_IDS, stale=frozenset({"2542"}))


def test_a_stale_roster_still_delivers_and_commits():
    state = ready_to_deliver().with_submission(ONE_STALE)
    assert decide(state, BRAKE) == DeliverDiff(state.diff)
    assert decide(state.with_delivered(), BRAKE) == CommitMaster(state.diff)


def test_a_stale_roster_turns_success_into_a_loud_failure():
    state = (
        ready_to_deliver()
        .with_submission(ONE_STALE)
        .with_delivered()
        .with_master_committed()
    )
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert (step.status, step.step, step.error) == (
        "failed",
        "refresh_rosters",
        "RosterRefreshFailed",
    )


def test_a_stuck_school_outranks_a_stale_roster():
    both = Submission(
        submitted=SCHOOL_IDS - {"2540"},
        stuck=frozenset({"2540"}),
        stale=frozenset({"2542"}),
    )
    state = ready_to_deliver(diff_result(new_count=0)).with_submission(both)
    step = decide(state, BRAKE)
    assert isinstance(step, Finish)
    assert step.error == "QuerySubmissionIncomplete"
