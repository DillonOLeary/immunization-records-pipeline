"""The runner loop, driven with stub executors and a fake clock.

The policy tests prove `decide` names the right steps; these prove the
loop executes them faithfully: polling at the interval, stopping at the
deadline, failing loudly mid-step with the master untouched, and writing
exactly one terminal event per run.
"""

import pytest

import mn_immunization.pipeline.execute as execute
from mn_immunization.gcp.storage import GcsObjectStore
from mn_immunization.ledger.memory import InMemoryRunLedger, InMemorySnapshotStore
from mn_immunization.pipeline.cycles import RunContext
from mn_immunization.pipeline.policy import DiffResult, Submission
from mn_immunization.sources.aisr.port import DistrictInfo, SchoolQueryInformation
from tests.fakes import FakeBucket, FakeDrive

SCHOOLS = 8
INTERVAL = 14400
DEADLINE = 72000


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", str(INTERVAL))
    monkeypatch.setenv("POLL_DEADLINE_SECONDS", str(DEADLINE))
    monkeypatch.setenv("DIFF_SANITY_FRACTION", "0.2")


def no_source(auth_url, api_url):
    raise AssertionError("executors are stubbed; no AISR session expected")


def make_ctx(tmp_path, schools: int = SCHOOLS) -> RunContext:
    return RunContext(
        ledger=InMemoryRunLedger(),
        snapshots=InMemorySnapshotStore(),
        objects=GcsObjectStore(FakeBucket()),
        drive=FakeDrive(),
        open_source=no_source,
        temp=tmp_path,
        auth_url="https://auth.test",
        api_url="https://api.test",
        district=DistrictInfo(iddis="0197", s3_upload_host="mock-s3-host"),
        schools=[
            SchoolQueryInformation(
                school_name=f"school-{i}",
                classification="N",
                school_id=str(1000 + i),
                email_contact="nurse@example.test",
                query_file_path="",
            )
            for i in range(schools)
        ],
    )


def make_diff(tmp_path, new=648, known=170_361, files=8, failures=0) -> DiffResult:
    return DiffResult(
        new_count=new,
        known_count=known,
        files_transformed=files,
        fetch_failures=failures,
        diff_path=tmp_path / "2026-07-23_new_vaccinations.csv",
        master_path=tmp_path / "all_known_vaccinations.csv",
    )


def stub_executors(
    monkeypatch, staged, diff, deliver_outcome="delivered", submission=None
):
    """Replace the I/O executors; the loop under test stays real.

    `staged` is the sequence of probe results (the last repeats); an
    exception in it is raised by that probe. `deliver_outcome` is
    "delivered", "already_delivered", or an exception to raise. Returns
    the ordered call log.
    """
    calls = []
    staged_iter = iter(staged)
    last = {"outcome": 0}

    def fake_submit(ctx):
        calls.append("submit")
        if submission is not None:
            return submission
        return Submission(submitted=frozenset(s.school_id for s in ctx.schools))

    def fake_probe(ctx, school_ids):
        calls.append("probe")
        try:
            last["outcome"] = next(staged_iter)
        except StopIteration:
            pass
        if isinstance(last["outcome"], Exception):
            raise last["outcome"]
        return last["outcome"]

    def fake_deliver(ctx, d):
        calls.append("deliver")
        if isinstance(deliver_outcome, Exception):
            raise deliver_outcome
        return deliver_outcome

    monkeypatch.setattr(execute, "_submit_queries", fake_submit)
    monkeypatch.setattr(execute, "_probe_staged", fake_probe)
    monkeypatch.setattr(
        execute, "_compute_diff", lambda ctx: (calls.append("compute"), diff)[1]
    )
    monkeypatch.setattr(execute, "_deliver_diff", fake_deliver)
    monkeypatch.setattr(
        execute, "_commit_master", lambda ctx, d: calls.append("commit")
    )
    return calls


def run(ctx, fake_clock):
    return execute.run_to_completion(
        ctx, sleep=fake_clock.sleep, clock=fake_clock.clock
    )


def test_happy_path_runs_the_steps_in_order(env, monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(monkeypatch, staged=[SCHOOLS], diff=make_diff(tmp_path))
    fake = FakeClock()

    result = run(ctx, fake)

    assert calls == ["submit", "probe", "compute", "deliver", "commit"]
    assert result == {
        "status": "success",
        "files_transformed": 8,
        "new_records": 648,
    }
    assert ctx.ledger.event_types() == ["RunCompleted"]
    assert fake.sleeps == []


def test_polls_at_interval_until_staged(env, monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(monkeypatch, staged=[2, 5, 8], diff=make_diff(tmp_path))
    fake = FakeClock()

    result = run(ctx, fake)

    assert result["status"] == "success"
    assert fake.sleeps == [INTERVAL, INTERVAL]
    assert calls.count("probe") == 3


def test_nothing_staged_by_deadline_fails_loudly(env, monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(monkeypatch, staged=[0], diff=make_diff(tmp_path))
    fake = FakeClock()

    result = run(ctx, fake)

    assert result["status"] == "failed"
    assert sum(fake.sleeps) == DEADLINE
    assert "compute" not in calls
    assert ctx.ledger.event_types() == ["RunFailed"]
    assert ctx.ledger.events[0]["data"] == {
        "step": "awaiting_results",
        "error": "NoResultsStaged",
    }


def test_a_failed_probe_mid_wait_does_not_end_the_run(env, monkeypatch, tmp_path):
    # One AISR blip during the 20-hour wait (a failed login, a maintenance
    # page) used to be a RunFailed; now the loop keeps waiting.
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        monkeypatch,
        staged=[2, ConnectionError("aisr blip"), SCHOOLS],
        diff=make_diff(tmp_path),
    )
    fake = FakeClock()

    result = run(ctx, fake)

    assert result["status"] == "success"
    assert fake.sleeps == [INTERVAL, INTERVAL]
    assert calls.count("probe") == 3
    assert ctx.ledger.event_types() == ["RunCompleted"]


def test_probes_failing_through_the_deadline_fail_naming_the_error(
    env, monkeypatch, tmp_path
):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        monkeypatch, staged=[ConnectionError("aisr down")], diff=make_diff(tmp_path)
    )
    fake = FakeClock()

    result = run(ctx, fake)

    assert result["status"] == "failed"
    assert sum(fake.sleeps) == DEADLINE
    assert "compute" not in calls
    assert ctx.ledger.events[0]["data"] == {
        "step": "awaiting_results",
        "error": "ConnectionError",
    }


def test_partial_staging_past_deadline_proceeds(env, monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(monkeypatch, staged=[4], diff=make_diff(tmp_path))
    fake = FakeClock()

    result = run(ctx, fake)

    assert result["status"] == "success"
    assert sum(fake.sleeps) == DEADLINE
    assert calls[-3:] == ["compute", "deliver", "commit"]


def test_a_stuck_school_delivers_the_rest_then_fails_naming_it(
    env, monkeypatch, tmp_path
):
    ctx = make_ctx(tmp_path)
    ids = frozenset(s.school_id for s in ctx.schools)
    stuck = Submission(submitted=ids - {"1000"}, stuck=frozenset({"1000"}))
    calls = stub_executors(
        monkeypatch, staged=[SCHOOLS - 1], diff=make_diff(tmp_path), submission=stuck
    )

    result = run(ctx, FakeClock())

    assert calls == ["submit", "probe", "compute", "deliver", "commit"]
    assert result["status"] == "failed"
    assert result["stuck_schools"] == ["1000"]
    assert ctx.ledger.event_types() == ["RunFailed"]
    assert ctx.ledger.events[0]["data"] == {
        "step": "submit_queries",
        "error": "QuerySubmissionIncomplete",
        "stuck_schools": ["1000"],
        "failed_schools": [],
    }


def test_nothing_submitted_fails_without_waiting(env, monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    ids = frozenset(s.school_id for s in ctx.schools)
    calls = stub_executors(
        monkeypatch,
        staged=[0],
        diff=make_diff(tmp_path),
        submission=Submission(failed=ids),
    )
    fake = FakeClock()

    result = run(ctx, fake)

    assert calls == ["submit"]
    assert fake.sleeps == []
    assert result["status"] == "failed"
    assert ctx.ledger.events[0]["data"]["error"] == "NoQueriesSubmitted"


def test_staging_waits_only_for_submitted_schools(env, monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    ids = frozenset(s.school_id for s in ctx.schools)
    one_failed = Submission(submitted=ids - {"1003"}, failed=frozenset({"1003"}))
    probed = []
    calls = stub_executors(
        monkeypatch,
        staged=[SCHOOLS - 1],
        diff=make_diff(tmp_path),
        submission=one_failed,
    )
    real_probe = execute._probe_staged

    def recording_probe(ctx, school_ids):
        probed.append(school_ids)
        return real_probe(ctx, school_ids)

    monkeypatch.setattr(execute, "_probe_staged", recording_probe)
    fake = FakeClock()

    run(ctx, fake)

    assert probed == [ids - {"1003"}]
    assert fake.sleeps == []  # 7 of 7 expected schools staged at once
    assert "compute" in calls


def test_brake_blocks_before_delivery_and_commit(env, monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        monkeypatch, staged=[SCHOOLS], diff=make_diff(tmp_path, new=100_000)
    )

    result = run(ctx, FakeClock())

    assert result["status"] == "blocked"
    assert "deliver" not in calls
    assert "commit" not in calls
    assert ctx.ledger.event_types() == ["RunFailed"]
    assert ctx.ledger.events[0]["data"] == {
        "step": "diff_sanity",
        "error": "SuspiciousDiffVolume",
    }


def test_delivery_failure_fails_loudly_with_master_untouched(
    env, monkeypatch, tmp_path
):
    # The flaw this architecture exists to kill: a failed Drive upload used
    # to be a warning followed by RunCompleted, after the master had
    # already absorbed the records.
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        monkeypatch,
        staged=[SCHOOLS],
        diff=make_diff(tmp_path),
        deliver_outcome=ConnectionError("drive down"),
    )

    result = run(ctx, FakeClock())

    assert result["status"] == "failed"
    assert "ConnectionError" in result["reason"]
    assert "commit" not in calls
    assert ctx.ledger.event_types() == ["RunFailed"]
    assert ctx.ledger.events[0]["data"] == {
        "step": "deliver_diff",
        "error": "ConnectionError",
    }


def test_diff_already_delivered_still_commits_then_skips(env, monkeypatch, tmp_path):
    # A crashed prior run may have delivered without committing; the
    # rerun's job is to finish the commit, then record the skip.
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        monkeypatch,
        staged=[SCHOOLS],
        diff=make_diff(tmp_path),
        deliver_outcome="already_delivered",
    )

    result = run(ctx, FakeClock())

    assert result["status"] == "skipped"
    assert calls[-2:] == ["deliver", "commit"]
    assert ctx.ledger.event_types() == ["RunSkipped"]


def test_empty_diff_completes_without_delivering(env, monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    calls = stub_executors(
        monkeypatch, staged=[SCHOOLS], diff=make_diff(tmp_path, new=0)
    )

    result = run(ctx, FakeClock())

    assert result == {"status": "success", "files_transformed": 8, "new_records": 0}
    assert "deliver" not in calls
    assert "commit" not in calls


def test_missing_drive_folder_fails_before_any_step(env, monkeypatch, tmp_path):
    # Checked before SubmitQueries: a misconfigured delivery target must
    # not cost the period's one roster submission (and its nurse email).
    ctx = make_ctx(tmp_path)
    ctx.drive = None
    calls = stub_executors(monkeypatch, staged=[SCHOOLS], diff=make_diff(tmp_path))

    result = run(ctx, FakeClock())

    assert result["status"] == "failed"
    assert calls == []
    assert ctx.ledger.events[0]["data"] == {
        "step": "delivery",
        "error": "NoDriveFolder",
    }


def test_brake_fraction_parsing(monkeypatch):
    monkeypatch.delenv("DIFF_SANITY_FRACTION", raising=False)
    assert execute._brake_fraction() == 0.2
    monkeypatch.setenv("DIFF_SANITY_FRACTION", "off")
    assert execute._brake_fraction() is None
    monkeypatch.setenv("DIFF_SANITY_FRACTION", "0.5")
    assert execute._brake_fraction() == 0.5


# --- the real _deliver_diff, with only the Drive upload stubbed ---


def test_deliver_wins_claim_uploads_and_records(monkeypatch, tmp_path):
    ctx = make_ctx(tmp_path)
    diff = make_diff(tmp_path)
    diff.diff_path.write_text("1,2,MMR,01/01/2020\n", encoding="utf-8")

    outcome = execute._deliver_diff(ctx, diff)
    uploads = ctx.drive.uploads

    assert outcome == "delivered"
    assert uploads == [diff.diff_path.name]
    assert ctx.ledger.event_types() == ["Delivered"]
    assert f"{diff.diff_path.name[:10]}_diff" in ctx.ledger.claims


def test_deliver_claim_lost_without_evidence_delivers_anyway(monkeypatch, tmp_path):
    # The claimant crashed between claiming and uploading. Zero deliveries
    # is the unacceptable failure mode; deliver.
    ctx = make_ctx(tmp_path)
    diff = make_diff(tmp_path)
    ctx.ledger.claims[f"{diff.diff_path.name[:10]}_diff"] = {"run_id": "earlier"}
    diff.diff_path.write_text("1,2,MMR,01/01/2020\n", encoding="utf-8")

    outcome = execute._deliver_diff(ctx, diff)
    uploads = ctx.drive.uploads

    assert outcome == "delivered"
    assert uploads == [diff.diff_path.name]


def test_deliver_claim_lost_with_delivered_event_skips(monkeypatch, tmp_path):
    # Another run claimed AND recorded a Drive delivery: genuine duplicate,
    # skip it. This is the July 1 double-run incident staying dead.
    ctx = make_ctx(tmp_path)
    diff = make_diff(tmp_path)
    ctx.ledger.claims[f"{diff.diff_path.name[:10]}_diff"] = {"run_id": "earlier"}
    ctx.ledger.history.append(
        {
            "run_id": "earlier-run",
            "seq": 9,
            "type": "Delivered",
            "at": "2026-07-23T02:15:00",
            "data": {
                "file_name": diff.diff_path.name,
                "target": "drive",
                "remote_id": "drive-id-0",
            },
        }
    )
    diff.diff_path.write_text("1,2,MMR,01/01/2020\n", encoding="utf-8")

    outcome = execute._deliver_diff(ctx, diff)
    uploads = ctx.drive.uploads

    assert outcome == "already_delivered"
    assert uploads == []
