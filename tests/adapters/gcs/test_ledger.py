"""GCS ledger adapter tests against a fake bucket honoring generation
preconditions — the mechanism the claim guarantee rests on."""

import json
from datetime import datetime

import pytest

from mn_immunization.adapters.gcs.ledger import (
    GcsRunLedger,
    GcsSnapshotStore,
    recent_months,
)
from mn_immunization.workflow import events
from tests.fakes import FakeBucket


def fixed_now():
    return datetime(2026, 7, 22, 9, 0, 0)


@pytest.fixture
def bucket():
    return FakeBucket()


def test_append_writes_one_object_per_event_with_sequence(bucket):
    ledger = GcsRunLedger(bucket, run_id="download_x", now=fixed_now)
    ledger.append(events.run_started("download", "scheduled"))
    ledger.append(events.run_completed(schools=8))

    names = sorted(bucket.objects)
    assert names == [
        "ledger/2026/07/download_x/001_RunStarted.json",
        "ledger/2026/07/download_x/002_RunCompleted.json",
    ]
    payload = json.loads(bucket.objects[names[0]])
    assert payload["run_id"] == "download_x"
    assert payload["seq"] == 1
    assert payload["at"] == "2026-07-22T09:00:00"
    assert payload["data"] == {"kind": "download", "trigger": "scheduled"}


def test_claim_wins_once_across_separate_runs(bucket):
    first_run = GcsRunLedger(bucket, run_id="run-a", now=fixed_now)
    second_run = GcsRunLedger(bucket, run_id="run-b", now=fixed_now)

    assert first_run.claim("2026-07-22_diff") is True
    assert second_run.claim("2026-07-22_diff") is False
    assert second_run.claim("2026-07-23_diff") is True

    claim = json.loads(bucket.objects["ledger/claims/2026-07-22_diff"])
    assert claim["run_id"] == "run-a"


def test_snapshots_are_content_addressed_and_idempotent(bucket):
    store = GcsSnapshotStore(bucket)
    digest_a, path_a = store.put("1,2,MMR,01/15/2024\n")
    digest_b, path_b = store.put("1,2,MMR,01/15/2024\n")

    assert (digest_a, path_a) == (digest_b, path_b)
    assert path_a == f"snapshots/{digest_a}.csv"
    assert bucket.objects[path_a] == "1,2,MMR,01/15/2024\n"


def test_read_recent_runs_groups_and_orders(bucket):
    from mn_immunization.adapters.gcs.ledger import read_recent_runs

    early = GcsRunLedger(
        bucket, run_id="download_a", now=lambda: datetime(2026, 7, 1, 2, 0, 0)
    )
    early.append(events.run_started("download", "scheduled"))
    early.append(events.run_completed(schools=8))

    late = GcsRunLedger(
        bucket, run_id="query_b", now=lambda: datetime(2026, 7, 22, 9, 0, 0)
    )
    late.append(events.run_started("query", "manual"))

    runs = read_recent_runs(bucket, months=((2026, 7),))

    assert [r["run_id"] for r in runs] == ["query_b", "download_a"]
    assert [e["type"] for e in runs[1]["events"]] == ["RunStarted", "RunCompleted"]
    # query_b has no terminal event — exactly what status must surface
    assert runs[0]["events"][-1]["type"] == "RunStarted"


def test_recent_months_crosses_the_year_boundary():
    assert recent_months(datetime(2026, 1, 15), 2) == ((2026, 1), (2025, 12))
    assert recent_months(datetime(2026, 10, 1), 3) == (
        (2026, 10),
        (2026, 9),
        (2026, 8),
    )


def test_recent_runs_reads_this_and_last_month_including_other_runs(bucket):
    september = GcsRunLedger(
        bucket, run_id="run_sep", now=lambda: datetime(2026, 9, 27, 7, 0, 0)
    )
    september.append(events.run_started("run", "manual"))
    august = GcsRunLedger(
        bucket, run_id="run_aug", now=lambda: datetime(2026, 8, 28, 7, 0, 0)
    )
    august.append(events.run_started("run", "scheduled"))
    october = GcsRunLedger(
        bucket, run_id="run_oct", now=lambda: datetime(2026, 10, 1, 9, 0, 0)
    )
    october.append(events.run_started("canary", "manual"))

    runs = october.recent_runs()

    # This month and last month: August is out of the window.
    assert [r["run_id"] for r in runs] == ["run_oct", "run_sep"]


def test_held_claims_returns_payloads_under_a_prefix(bucket):
    ledger = GcsRunLedger(bucket, run_id="run-a", now=fixed_now)
    ledger.claim("2026-07_query_2542")
    ledger.claim("2026-07_query_2543")
    ledger.claim("2026-07-22_diff")

    held = ledger.held_claims("2026-07_query")

    assert sorted(held) == ["2026-07_query_2542", "2026-07_query_2543"]
    assert held["2026-07_query_2542"]["run_id"] == "run-a"


def test_a_run_can_release_only_its_own_unchanged_claim(bucket):
    from google.api_core.exceptions import PreconditionFailed

    mine = GcsRunLedger(bucket, run_id="run-a", now=fixed_now)
    theirs = GcsRunLedger(bucket, run_id="run-b", now=fixed_now)
    assert mine.claim("2026-07_query_2542")

    with pytest.raises(ValueError):
        theirs.release("2026-07_query_2542")  # never someone else's

    mine.release("2026-07_query_2542")
    assert "ledger/claims/2026-07_query_2542" not in bucket.objects
    assert theirs.claim("2026-07_query_2542")  # free again

    assert mine.claim("2026-07_query_2543")
    bucket.write("ledger/claims/2026-07_query_2543", "{}")  # rewritten since
    with pytest.raises(PreconditionFailed):
        mine.release("2026-07_query_2543")
