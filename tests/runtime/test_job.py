"""Job entrypoint tests: settings, dispatch, trigger plumbing, exit codes.

Every test passes `env` and `build`, so no test can construct a real
cloud client from whatever credentials the machine happens to have.
"""

import json

import mn_immunization.runtime.job as job

ENV = {"DATA_BUCKET": "test-bucket"}
SERVICES = object()  # stands in for Services; the fake cycles only pass it on


def fake_build(settings):
    assert settings.data_bucket == "test-bucket"
    return SERVICES


def main(argv, env=ENV):
    return job.main(argv, env=env, build=fake_build)


def test_missing_bucket_returns_2_naming_the_variable(capsys):
    assert main(["run"], env={}) == 2
    assert "DATA_BUCKET is not set" in capsys.readouterr().err


def test_malformed_setting_returns_2_without_echoing_the_value(capsys):
    env = {**ENV, "POLL_INTERVAL_SECONDS": "four-hours-ish"}
    assert main(["run"], env=env) == 2
    err = capsys.readouterr().err
    assert "POLL_INTERVAL_SECONDS must be an integer" in err
    assert "four-hours-ish" not in err


def test_dispatches_cycle_with_services_and_trigger(monkeypatch):
    calls = []

    def fake_cycle(services, trigger="scheduled"):
        calls.append((services, trigger))
        return {"status": "success"}

    monkeypatch.setitem(job.CYCLES, "run", fake_cycle)

    assert main(["run", "--trigger", "manual"]) == 0
    assert calls == [(SERVICES, "manual")]


def test_trigger_defaults_to_scheduled(monkeypatch):
    calls = []
    monkeypatch.setitem(
        job.CYCLES,
        "canary",
        lambda services, trigger: calls.append(trigger) or {"status": "success"},
    )

    assert main(["canary"]) == 0
    assert calls == ["scheduled"]


def test_trigger_env_sets_the_default(monkeypatch):
    calls = []
    monkeypatch.setitem(
        job.CYCLES,
        "canary",
        lambda services, trigger: calls.append(trigger) or {"status": "success"},
    )

    assert main(["canary"], env={**ENV, "TRIGGER": "manual"}) == 0
    assert calls == ["manual"]


def test_skipped_status_is_success_exit(monkeypatch):
    monkeypatch.setitem(job.CYCLES, "run", lambda s, trigger: {"status": "skipped"})
    assert main(["run"]) == 0


def test_failed_status_exits_1_so_the_alert_fires(monkeypatch):
    monkeypatch.setitem(job.CYCLES, "run", lambda s, trigger: {"status": "failed"})
    assert main(["run"]) == 1


def test_uncaught_exception_prints_class_and_location_never_the_message(
    monkeypatch, capsys
):
    # Exception messages can carry response bodies or field values; the job
    # must exit 1 with only the class and code location on its output.
    def exploding_cycle(services, trigger="scheduled"):
        raise ValueError("Zelda Canaryfield 1999-12-31")

    monkeypatch.setitem(job.CYCLES, "run", exploding_cycle)

    assert main(["run"]) == 1

    out = capsys.readouterr()
    assert "Zelda" not in out.out + out.err
    result = json.loads(out.out.strip().splitlines()[-1])
    assert result["status"] == "failed"
    assert result["error"] == "ValueError"
    assert any("exploding_cycle" in frame for frame in result["where"])


def test_a_failure_building_services_is_caught_the_same_way(capsys):
    def broken_build(settings):
        raise PermissionError("no credentials for Zelda")

    assert job.main(["run"], env=ENV, build=broken_build) == 1
    out = capsys.readouterr().out
    assert "Zelda" not in out
    assert json.loads(out.strip().splitlines()[-1])["error"] == "PermissionError"
