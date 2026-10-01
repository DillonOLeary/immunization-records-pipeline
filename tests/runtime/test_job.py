"""Job entrypoint tests: dispatch, trigger plumbing, and env guards."""

import json

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
    monkeypatch.setitem(job.CYCLES, "run", lambda b, trigger: {"status": "skipped"})
    assert job.main(["run"]) == 0


def test_uncaught_exception_prints_class_and_location_never_the_message(
    monkeypatch, capsys
):
    # Exception messages can carry response bodies or field values; the job
    # must exit 1 with only the class and code location on its output.
    def exploding_cycle(bucket_name, trigger="scheduled"):
        raise ValueError("Zelda Canaryfield 1999-12-31")

    monkeypatch.setenv("DATA_BUCKET", "test-bucket")
    monkeypatch.setitem(job.CYCLES, "run", exploding_cycle)

    assert job.main(["run"]) == 1

    out = capsys.readouterr()
    assert "Zelda" not in out.out + out.err
    result = json.loads(out.out.strip().splitlines()[-1])
    assert result["status"] == "failed"
    assert result["error"] == "ValueError"
    assert any("exploding_cycle" in frame for frame in result["where"])
