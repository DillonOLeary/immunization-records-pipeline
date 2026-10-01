"""ImportConfirmed detection: delete-as-ack against the Drive folder.

The Drive protocol is that staff delete a delivered file after importing
it. `record_import_confirmations` reads the ledger for Delivered files,
lists the folder, and records ImportConfirmed for the ones now gone.
Everything is best-effort: a listing failure must never sink the run.
"""

import mn_immunization.pipeline.execute as execute
from mn_immunization.gcp.storage import GcsObjectStore
from mn_immunization.ledger.memory import InMemoryRunLedger, InMemorySnapshotStore
from mn_immunization.pipeline.cycles import RunContext
from mn_immunization.sources.aisr.port import DistrictInfo
from tests.fakes import FakeBucket, FakeDrive


def delivered_event(file_name: str, run_id: str, seq: int = 1) -> dict:
    return {
        "run_id": run_id,
        "seq": seq,
        "type": "Delivered",
        "at": "2026-07-23T02:15:00",
        "data": {"file_name": file_name, "target": "drive", "remote_id": "x"},
    }


def confirmed_event(file_name: str, run_id: str, seq: int = 2) -> dict:
    return {
        "run_id": run_id,
        "seq": seq,
        "type": "ImportConfirmed",
        "at": "2026-07-24T02:15:00",
        "data": {"file_name": file_name, "how": "deleted from Drive"},
    }


def make_ctx(ledger_payloads: list[dict], tmp_path) -> RunContext:
    ledger = InMemoryRunLedger(history=ledger_payloads)
    return RunContext(
        ledger=ledger,
        snapshots=InMemorySnapshotStore(),
        objects=GcsObjectStore(FakeBucket()),
        drive=FakeDrive(),
        open_source=lambda auth_url, api_url: None,
        temp=tmp_path,
        auth_url="https://auth.test",
        api_url="https://api.test",
        district=DistrictInfo(iddis="0197", s3_upload_host="mock-s3-host"),
        schools=[],
    )


def stub_folder(ctx, present: set[str]) -> None:
    """The files still sitting in the Drive folder."""
    ctx.drive.files = dict.fromkeys(present, "")


def test_absent_delivered_file_is_confirmed(tmp_path):
    ctx = make_ctx(
        [delivered_event("2026-07-23_new_vaccinations.csv", "run-a")], tmp_path
    )
    stub_folder(ctx, present=set())  # staff deleted it

    execute.record_import_confirmations(ctx)

    assert ctx.ledger.event_types() == ["ImportConfirmed"]
    assert ctx.ledger.events[0]["data"] == {
        "file_name": "2026-07-23_new_vaccinations.csv",
        "how": "deleted from Drive",
    }


def test_present_delivered_file_is_not_confirmed(tmp_path):
    name = "2026-07-23_new_vaccinations.csv"
    ctx = make_ctx([delivered_event(name, "run-a")], tmp_path)
    stub_folder(ctx, present={name})  # still awaiting import

    execute.record_import_confirmations(ctx)

    assert ctx.ledger.event_types() == []


def test_already_confirmed_file_is_not_confirmed_again(tmp_path):
    name = "2026-07-23_new_vaccinations.csv"
    ctx = make_ctx(
        [delivered_event(name, "run-a"), confirmed_event(name, "run-b")], tmp_path
    )
    stub_folder(ctx, present=set())

    execute.record_import_confirmations(ctx)

    assert ctx.ledger.event_types() == []


def test_stale_present_file_warns(tmp_path, caplog):
    old = "2020-01-01_new_vaccinations.csv"  # far past IMPORT_REMINDER_DAYS
    ctx = make_ctx([delivered_event(old, "run-a")], tmp_path)
    stub_folder(ctx, present={old})

    with caplog.at_level("WARNING"):
        execute.record_import_confirmations(ctx)

    assert ctx.ledger.event_types() == []
    assert any("awaiting import" in r.message for r in caplog.records)


def test_listing_failure_is_swallowed(tmp_path):
    ctx = make_ctx(
        [delivered_event("2026-07-23_new_vaccinations.csv", "run-a")], tmp_path
    )

    ctx.drive = FakeDrive(list_error=ConnectionError("drive down"))

    execute.record_import_confirmations(ctx)  # must not raise

    assert ctx.ledger.event_types() == []


def test_no_folder_configured_is_a_noop(tmp_path):
    ctx = make_ctx(
        [delivered_event("2026-07-23_new_vaccinations.csv", "run-a")], tmp_path
    )
    ctx.drive = None

    execute.record_import_confirmations(ctx)

    assert ctx.ledger.event_types() == []
