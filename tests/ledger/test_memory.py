"""In-memory ledger tests."""

from datetime import datetime

from mn_immunization.ledger import events
from mn_immunization.ledger.memory import InMemoryRunLedger, InMemorySnapshotStore


def fixed_now():
    return datetime(2026, 7, 22, 9, 0, 0)


def test_append_stamps_run_id_seq_and_time():
    ledger = InMemoryRunLedger(run_id="run-1", now=fixed_now)
    ledger.append(events.run_started("download", "scheduled"))
    ledger.append(events.run_completed(schools=8))

    assert ledger.event_types() == ["RunStarted", "RunCompleted"]
    assert ledger.events[0]["run_id"] == "run-1"
    assert ledger.events[0]["seq"] == 1
    assert ledger.events[1]["seq"] == 2
    assert ledger.events[0]["at"] == "2026-07-22T09:00:00"


def test_claim_wins_exactly_once():
    ledger = InMemoryRunLedger()
    assert ledger.claim("2026-07-22_diff") is True
    assert ledger.claim("2026-07-22_diff") is False
    assert ledger.claim("2026-07-23_diff") is True


def test_snapshot_store_is_content_addressed():
    store = InMemorySnapshotStore()
    digest_a, path_a = store.put("a,b,c\n")
    digest_b, path_b = store.put("a,b,c\n")
    digest_c, path_c = store.put("x,y,z\n")

    assert (digest_a, path_a) == (digest_b, path_b)
    assert path_a != path_c
    assert store.snapshots[path_a] == "a,b,c\n"
