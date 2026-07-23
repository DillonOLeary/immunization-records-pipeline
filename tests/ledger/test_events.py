"""Event factory tests: shape, and the no-PHI rule."""

from mn_immunization.ledger import events


def test_run_started():
    event = events.run_started(kind="run", trigger="scheduled")
    assert event.type == "RunStarted"
    assert event.data == {"kind": "run", "trigger": "scheduled"}


def test_terminal_types_cover_the_three_outcomes():
    assert events.run_completed(schools=8).type in events.TERMINAL_TYPES
    assert events.run_skipped("already delivered").type in events.TERMINAL_TYPES
    assert events.run_failed("download", "TimeoutError").type in events.TERMINAL_TYPES
    assert events.run_started("query", "manual").type not in events.TERMINAL_TYPES


def test_events_carry_hashes_and_counts_not_content():
    # The convention every event follows: identifiers, hashes, counts,
    # reasons. Never names, never record rows.
    event = events.records_fetched(
        school_id="1234", content_hash="ab" * 32, byte_size=2048
    )
    assert set(event.data) == {"school_id", "content_hash", "byte_size"}


def test_diff_computed_fields():
    event = events.diff_computed(
        new_count=12,
        total_count=4200,
        known_hash="k" * 64,
        diff_hash="d" * 64,
    )
    assert event.data["new_count"] == 12
    assert event.data["diff_hash"] == "d" * 64


def test_master_committed_references_its_snapshot():
    event = events.master_committed(
        master_hash="m" * 64, record_count=171_009, snapshot_path="snapshots/abc.csv"
    )
    assert event.data["record_count"] == 171_009
    assert event.data["snapshot_path"] == "snapshots/abc.csv"


def test_delivered_defaults_remote_id_to_empty():
    assert events.delivered("x.csv", "drive").data["remote_id"] == ""
