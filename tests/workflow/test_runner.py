"""The runner loop, driven with stub executors and a fake clock.

The policy tests prove `decide` names the right steps; these prove the
loop executes them faithfully: one staging probe per execution, ending
"waiting" (period still open) before the deadline and moving on after
it, failing loudly mid-step with the master untouched, and writing
exactly one terminal event per execution, after closing the period
unless it is waiting. The stubs are injected as an `Executors` table: no
monkeypatching.
"""

from dataclasses import replace
from datetime import timedelta

import mn_immunization.workflow.runner as runner
from mn_immunization.records.hashing import sha256_hex
from mn_immunization.workflow.policy import DiffResult, Submission
from mn_immunization.workflow.ports import School
from mn_immunization.workflow.runner import Executors
from mn_immunization.workflow.settings import Settings
from mn_immunization.workflow.steps import delivery
from tests.fakes import DISTRICT, FakeClock, make_run_context

SCHOOLS = 8
DEADLINE = 72000
SETTINGS = Settings(
    data_bucket="test-bucket",
    time_zone=DISTRICT,
    poll_deadline_seconds=DEADLINE,
    brake_fraction=0.2,
)


def make_ctx(tmp_path, schools: int = SCHOOLS, opened_seconds_ago: float = 0):
    """A period opened `opened_seconds_ago`: at or past DEADLINE, a short
    staging count no longer waits."""
    clock = FakeClock()
    return make_run_context(
        tmp_path,
        settings=SETTINGS,
        clock=clock.as_clock(),
        opened_at=clock.now() - timedelta(seconds=opened_seconds_ago),
        schools=[
            School(id=str(1000 + i), name=f"school-{i}", roster_path="")
            for i in range(schools)
        ],
    )


def past_deadline(tmp_path):
    return make_ctx(tmp_path, opened_seconds_ago=DEADLINE)


def make_diff(tmp_path, new=648, known=170_361, files=8, failures=0) -> DiffResult:
    return DiffResult(
        new_count=new,
        known_count=known,
        files_transformed=files,
        fetch_failures=failures,
        diff_path=tmp_path / "2026-07-23_new_vaccinations.csv",
        master_path=tmp_path / "all_known_vaccinations.csv",
    )


class Stubs(list):
    """The ordered call log, plus the Executors that write to it."""

    executors: Executors


def stub_executors(staged, diff, deliver_outcome="delivered", submission=None):
    """Stub executors; the loop under test stays real.

    `staged` is the probe's result, or an exception for it to raise.
    `deliver_outcome` is "delivered", "already_delivered", or an exception
    to raise. Returns the call log, carrying the executors as `.executors`.
    """
    calls = Stubs()

    def fake_submit(ctx):
        calls.append("submit")
        if submission is not None:
            return submission
        return Submission(submitted=frozenset(s.id for s in ctx.schools))

    def fake_probe(ctx, school_ids):
        calls.append("probe")
        if isinstance(staged, Exception):
            raise staged
        return staged

    def fake_deliver(ctx, d):
        calls.append("deliver")
        if isinstance(deliver_outcome, Exception):
            raise deliver_outcome
        return deliver_outcome

    calls.executors = Executors(
        submit=fake_submit,
        probe=fake_probe,
        compute=lambda ctx: (calls.append("compute"), diff)[1],
        deliver=fake_deliver,
        commit=lambda ctx, d: calls.append("commit"),
    )
    return calls


def run(ctx, calls):
    return runner.run_to_completion(ctx, calls.executors)


def closed_as(ctx) -> str:
    (event,) = [e for e in ctx.ledger.events if e["type"] == "PeriodClosed"]
    assert event["data"]["period"] == ctx.period
    return event["data"]["outcome"]


def test_happy_path_runs_the_steps_in_order(tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(staged=SCHOOLS, diff=make_diff(tmp_path))

    result = run(ctx, calls)

    assert calls == ["submit", "probe", "compute", "deliver", "commit"]
    assert result == {
        "status": "success",
        "files_transformed": 8,
        "new_records": 648,
    }
    assert ctx.ledger.event_types() == ["PeriodClosed", "RunCompleted"]
    assert closed_as(ctx) == "success"


def test_a_short_count_before_the_deadline_ends_the_execution_waiting(tmp_path):
    # Nothing sleeps: the execution ends, the period stays open, and the
    # next tick probes again.
    ctx = make_ctx(tmp_path, opened_seconds_ago=DEADLINE - 1)
    calls = stub_executors(staged=2, diff=make_diff(tmp_path))

    result = run(ctx, calls)

    assert result == {"status": "waiting", "reason": "2/8 schools have results staged"}
    assert calls == ["submit", "probe"]
    assert ctx.ledger.event_types() == ["RunWaiting"]


def test_nothing_staged_by_the_deadline_fails_loudly(tmp_path):
    ctx = past_deadline(tmp_path)
    calls = stub_executors(staged=0, diff=make_diff(tmp_path))

    result = run(ctx, calls)

    assert result["status"] == "failed"
    assert "compute" not in calls
    assert ctx.ledger.event_types() == ["PeriodClosed", "RunFailed"]
    assert closed_as(ctx) == "failed"
    assert ctx.ledger.events[-1]["data"] == {
        "step": "awaiting_results",
        "error": "NoResultsStaged",
    }


def test_a_failed_probe_before_the_deadline_waits(tmp_path):
    # One AISR blip (a failed login, a maintenance page) is not a failed
    # period: the next tick looks again.
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        staged=ConnectionError("aisr blip"), diff=make_diff(tmp_path)
    )

    result = run(ctx, calls)

    assert result["status"] == "waiting"
    assert ctx.ledger.event_types() == ["RunWaiting"]


def test_a_failing_probe_at_the_deadline_fails_naming_the_error(tmp_path):
    ctx = past_deadline(tmp_path)
    calls = stub_executors(
        staged=ConnectionError("aisr down"), diff=make_diff(tmp_path)
    )

    result = run(ctx, calls)

    assert result["status"] == "failed"
    assert "compute" not in calls
    assert ctx.ledger.events[-1]["data"] == {
        "step": "awaiting_results",
        "error": "ConnectionError",
    }


def test_partial_staging_past_deadline_proceeds(tmp_path):
    ctx = past_deadline(tmp_path)
    calls = stub_executors(staged=4, diff=make_diff(tmp_path))

    result = run(ctx, calls)

    assert result["status"] == "success"
    assert calls[-3:] == ["compute", "deliver", "commit"]


def test_a_stuck_school_delivers_the_rest_then_fails_naming_it(tmp_path):
    ctx = make_ctx(tmp_path)
    ids = frozenset(s.id for s in ctx.schools)
    stuck = Submission(submitted=ids - {"1000"}, stuck=frozenset({"1000"}))
    calls = stub_executors(
        staged=SCHOOLS - 1, diff=make_diff(tmp_path), submission=stuck
    )

    result = run(ctx, calls)

    assert calls == ["submit", "probe", "compute", "deliver", "commit"]
    assert result["status"] == "failed"
    assert result["stuck_schools"] == ["1000"]
    assert ctx.ledger.event_types() == ["PeriodClosed", "RunFailed"]
    assert ctx.ledger.events[-1]["data"] == {
        "step": "submit_queries",
        "error": "QuerySubmissionIncomplete",
        "stuck_schools": ["1000"],
        "failed_schools": [],
    }


def test_nothing_submitted_fails_without_waiting(tmp_path):
    ctx = make_ctx(tmp_path)
    ids = frozenset(s.id for s in ctx.schools)
    calls = stub_executors(
        staged=0,
        diff=make_diff(tmp_path),
        submission=Submission(failed=ids),
    )

    result = run(ctx, calls)

    assert calls == ["submit"]
    assert result["status"] == "failed"
    assert ctx.ledger.events[-1]["data"]["error"] == "NoQueriesSubmitted"


def test_staging_waits_only_for_submitted_schools(tmp_path):
    ctx = make_ctx(tmp_path)
    ids = frozenset(s.id for s in ctx.schools)
    one_failed = Submission(submitted=ids - {"1003"}, failed=frozenset({"1003"}))
    probed = []
    calls = stub_executors(
        staged=SCHOOLS - 1,
        diff=make_diff(tmp_path),
        submission=one_failed,
    )
    stubbed_probe = calls.executors.probe

    def recording_probe(ctx, school_ids):
        probed.append(school_ids)
        return stubbed_probe(ctx, school_ids)

    calls.executors = replace(calls.executors, probe=recording_probe)

    run(ctx, calls)

    assert probed == [ids - {"1003"}]
    assert "compute" in calls  # 7 of 7 expected schools staged at once


def test_brake_blocks_before_delivery_and_commit(tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(staged=SCHOOLS, diff=make_diff(tmp_path, new=100_000))

    result = run(ctx, calls)

    assert result["status"] == "blocked"
    assert "deliver" not in calls
    assert "commit" not in calls
    assert ctx.ledger.event_types() == ["PeriodClosed", "RunFailed"]
    assert closed_as(ctx) == "blocked"
    assert ctx.ledger.events[-1]["data"] == {
        "step": "diff_sanity",
        "error": "SuspiciousDiffVolume",
    }


def test_delivery_failure_fails_loudly_with_master_untouched(tmp_path):
    # The flaw this architecture exists to kill: a failed Drive upload used
    # to be a warning followed by RunCompleted, after the master had
    # already absorbed the records.
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        staged=SCHOOLS,
        diff=make_diff(tmp_path),
        deliver_outcome=ConnectionError("drive down"),
    )

    result = run(ctx, calls)

    assert result["status"] == "failed"
    assert "ConnectionError" in result["reason"]
    assert "commit" not in calls
    assert ctx.ledger.event_types() == ["PeriodClosed", "RunFailed"]
    assert closed_as(ctx) == "failed"
    assert ctx.ledger.events[-1]["data"] == {
        "step": "deliver_diff",
        "error": "ConnectionError",
    }


def test_diff_already_delivered_still_commits_then_skips(tmp_path):
    # A crashed prior run may have delivered without committing; the
    # rerun's job is to finish the commit, then record the skip.
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        staged=SCHOOLS,
        diff=make_diff(tmp_path),
        deliver_outcome="already_delivered",
    )

    result = run(ctx, calls)

    assert result["status"] == "skipped"
    assert calls[-2:] == ["deliver", "commit"]
    assert ctx.ledger.event_types() == ["PeriodClosed", "RunSkipped"]


def test_empty_diff_completes_without_delivering(tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(staged=SCHOOLS, diff=make_diff(tmp_path, new=0))

    result = run(ctx, calls)

    assert result == {"status": "success", "files_transformed": 8, "new_records": 0}
    assert "deliver" not in calls
    assert "commit" not in calls


def test_missing_drive_folder_fails_before_any_step(tmp_path):
    # Checked before SubmitQueries: a misconfigured delivery target must
    # not cost the period's one roster submission (and its nurse email).
    ctx = make_ctx(tmp_path)
    ctx.delivery = None
    calls = stub_executors(staged=SCHOOLS, diff=make_diff(tmp_path))

    result = run(ctx, calls)

    assert result["status"] == "failed"
    assert calls == []
    assert closed_as(ctx) == "failed"
    assert ctx.ledger.events[-1]["data"] == {
        "step": "delivery",
        "error": "NoDriveFolder",
    }


# --- the real deliver_diff: at most once per diff *content* ---

DIFF_TEXT = "1,2,MMR,01/01/2020\n"


def write_diff(tmp_path, text=DIFF_TEXT):
    diff = make_diff(tmp_path)
    diff.diff_path.write_text(text, encoding="utf-8")
    return diff


def claim_key(diff, text=DIFF_TEXT):
    return f"{diff.diff_path.name[:10]}_diff_{sha256_hex(text)[:16]}"


def prior_delivery(ctx, file_name, text):
    ctx.ledger.history.append(
        {
            "run_id": "earlier-run",
            "seq": 9,
            "type": "Delivered",
            "at": "2026-07-23T02:15:00",
            "data": {
                "file_name": file_name,
                "target": "drive",
                "remote_id": "drive-id-0",
                "content_hash": sha256_hex(text),
            },
        }
    )


def test_deliver_wins_the_content_claim_uploads_and_records(tmp_path):
    ctx = make_ctx(tmp_path)
    diff = write_diff(tmp_path)

    assert delivery.deliver_diff(ctx, diff) == "delivered"

    assert ctx.delivery.uploads == [diff.diff_path.name]
    assert claim_key(diff) in ctx.ledger.claims
    (event,) = ctx.ledger.events
    assert event["data"]["content_hash"] == sha256_hex(DIFF_TEXT)


def test_claim_lost_without_evidence_delivers_anyway(tmp_path):
    # The claimant crashed between claiming and uploading. Zero deliveries
    # is the unacceptable failure mode; deliver.
    ctx = make_ctx(tmp_path)
    diff = write_diff(tmp_path)
    ctx.ledger.claims[claim_key(diff)] = {"run_id": "earlier"}

    assert delivery.deliver_diff(ctx, diff) == "delivered"
    assert ctx.delivery.uploads == [diff.diff_path.name]


def test_the_same_content_already_delivered_is_skipped(tmp_path):
    # Another run claimed AND delivered this exact diff (a crash before its
    # commit, then this rerun): skip the upload. The July 1 double-run
    # incident stays dead.
    ctx = make_ctx(tmp_path)
    diff = write_diff(tmp_path)
    ctx.ledger.claims[claim_key(diff)] = {"run_id": "earlier"}
    prior_delivery(ctx, diff.diff_path.name, DIFF_TEXT)

    assert delivery.deliver_diff(ctx, diff) == "already_delivered"
    assert ctx.delivery.uploads == []


def test_a_different_diff_the_same_day_is_delivered_under_its_own_name(tmp_path):
    # Found 2026-10-01: a second run the same day with *new* records saw
    # the date claim taken and a Delivered event with the same file name,
    # called it "already delivered", and would have committed its records
    # to the master without staff ever receiving them.
    ctx = make_ctx(tmp_path)
    diff = write_diff(tmp_path, text="9,9,DTaP,02/02/2021\n")
    prior_delivery(ctx, diff.diff_path.name, DIFF_TEXT)  # earlier, other content

    assert delivery.deliver_diff(ctx, diff) == "delivered"

    stem = diff.diff_path.name.removesuffix(".csv")
    assert ctx.delivery.uploads == [f"{stem}_2.csv"]
    assert ctx.delivery.files[f"{stem}_2.csv"] == "9,9,DTaP,02/02/2021\n"


def test_a_delivery_recorded_before_hashes_never_suppresses_a_diff(tmp_path):
    # Delivered events written before content hashes carry none, so they
    # can only make a new diff take a fresh name, never skip it.
    ctx = make_ctx(tmp_path)
    diff = write_diff(tmp_path)
    prior_delivery(ctx, diff.diff_path.name, DIFF_TEXT)
    ctx.ledger.history[-1]["data"].pop("content_hash")

    assert delivery.deliver_diff(ctx, diff) == "delivered"
    assert ctx.delivery.uploads == [diff.diff_path.name.replace(".csv", "_2.csv")]
