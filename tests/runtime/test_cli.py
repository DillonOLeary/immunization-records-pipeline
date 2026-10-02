"""CLI entrypoint tests: parsing and dispatch. The CLI is status-only;
everything that changes state runs as the Cloud Run Job."""

from datetime import UTC, datetime

import pytest

import mn_immunization.runtime.cli as cli
from mn_immunization.adapters.gcs.ledger import GcsRunLedger
from mn_immunization.workflow import events
from tests.fakes import FakeBucket


def test_command_is_required():
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args([])


def test_status_requires_bucket():
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["status"])


def test_dispatches_status_with_bucket_and_limit(monkeypatch):
    calls = []
    monkeypatch.setitem(
        cli.COMMANDS, "status", lambda args: calls.append((args.bucket, args.limit))
    )
    assert cli.main(["status", "--bucket", "test-bucket", "--limit", "3"]) == 0
    assert calls == [("test-bucket", 3)]


def test_stuck_claims_are_claims_without_a_submission_event(monkeypatch):
    # 2542 was submitted and recorded; 2543 was claimed but never recorded
    # (stuck); last month's claims are all accounted for.
    monkeypatch.delenv("QUERY_PERIOD_FORMAT", raising=False)
    now = datetime(2026, 10, 28, 9, 0, 0)
    bucket = FakeBucket()
    run = GcsRunLedger(bucket, run_id="run_oct", now=lambda: now)
    run.claim("2026-10_query_2542")
    run.append(events.query_submitted("2542", "hash", period="2026-10"))
    run.claim("2026-10_query_2543")
    september = GcsRunLedger(
        bucket, run_id="run_sep", now=lambda: datetime(2026, 9, 27, 7, 0, 0)
    )
    september.claim("2026-09_query_2542")
    september.append(events.query_submitted("2542", "hash", period="2026-09"))

    stuck = cli.stuck_claims(bucket, now)

    assert [key for key, _ in stuck] == ["2026-10_query_2543"]
    assert stuck[0][1]["run_id"] == "run_oct"


def test_status_prints_the_release_command_for_a_stuck_claim(monkeypatch, capsys):
    monkeypatch.delenv("QUERY_PERIOD_FORMAT", raising=False)
    bucket = FakeBucket()
    GcsRunLedger(bucket, run_id="run_x", now=datetime.now).claim(
        f"{datetime.now(UTC):%Y-%m}_query_2543"
    )
    monkeypatch.setattr(
        cli,
        "get_storage_client",
        lambda: type("C", (), {"bucket": lambda s, n: bucket})(),
    )

    cli.main(["status", "--bucket", "data-bucket"])

    out = capsys.readouterr().out
    assert "STUCK ROSTER CLAIMS" in out
    assert f"gs://data-bucket/ledger/claims/{datetime.now(UTC):%Y-%m}_query_2543" in out


def test_stuck_claims_cover_periods_named_in_the_ledger(monkeypatch):
    # A per-day cadence (QUERY_PERIOD_FORMAT=%Y-%m-%d) has periods the
    # month-based guess never names; the ledger's PeriodOpened does.
    monkeypatch.delenv("QUERY_PERIOD_FORMAT", raising=False)
    now = datetime(2026, 10, 28, 9, 0, 0)
    bucket = FakeBucket()
    run = GcsRunLedger(bucket, run_id="run_x", now=lambda: now)
    run.append(events.period_opened("2026-10-26"))
    run.claim("2026-10-26_query_2543")

    assert [key for key, _ in cli.stuck_claims(bucket, now)] == [
        "2026-10-26_query_2543"
    ]


def test_status_names_the_open_period(monkeypatch, capsys):
    bucket = FakeBucket()
    run = GcsRunLedger(bucket, run_id="run_x", now=lambda: datetime.now(UTC))
    run.append(events.run_started("run", "scheduled"))
    run.append(events.period_opened("2026-10"))
    run.append(events.run_waiting("3/8 schools have results staged"))
    monkeypatch.setattr(
        cli,
        "get_storage_client",
        lambda: type("C", (), {"bucket": lambda s, n: bucket})(),
    )

    cli.main(["status", "--bucket", "data-bucket"])

    out = capsys.readouterr().out
    assert "OPEN PERIOD 2026-10" in out
    assert "RunWaiting  reason=3/8 schools have results staged" in out
