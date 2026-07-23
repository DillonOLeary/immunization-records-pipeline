"""Job entrypoint tests: dispatch, trigger plumbing, and env guards."""

import mn_immunization.runtime.job as job


def test_missing_bucket_returns_2(monkeypatch):
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    assert job.main(["run"]) == 2


def test_dispatches_cycle_with_trigger(monkeypatch):
    calls = []

    def fake_cycle(bucket_name, trigger="scheduled"):
        calls.append((bucket_name, trigger))
        return {"status": "success"}

    monkeypatch.setenv("DATA_BUCKET", "test-bucket")
    monkeypatch.setitem(job.CYCLES, "run", fake_cycle)

    assert job.main(["run", "--trigger", "manual"]) == 0
    assert calls == [("test-bucket", "manual")]


def test_trigger_defaults_to_scheduled(monkeypatch):
    calls = []
    monkeypatch.setenv("DATA_BUCKET", "test-bucket")
    monkeypatch.delenv("TRIGGER", raising=False)
    monkeypatch.setitem(
        job.CYCLES,
        "canary",
        lambda bucket_name, trigger: calls.append(trigger) or {"status": "success"},
    )

    assert job.main(["canary"]) == 0
    assert calls == ["scheduled"]


def test_skipped_status_is_success_exit(monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-bucket")
    monkeypatch.setitem(
        job.CYCLES, "run", lambda b, trigger: {"status": "skipped"}
    )
    assert job.main(["run"]) == 0
