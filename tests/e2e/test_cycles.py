"""Characterization of every cycle, end to end, through the job entrypoint.

Each scenario pins what a run does to the outside world: the ledger events
it writes (exact sequence), what lands in Drive (exact text), what happens
to the master, which rosters reach MIIC, and the exit code the alert keys
on. The autouse PHI scan (conftest) runs on every one of them.
"""

from __future__ import annotations

import hashlib

from google.api_core.exceptions import ServiceUnavailable
from minnesota_immunization_mock.sample_data import expected_ic_rows

from tests.fakes import district_period

MASTER = "output/all_known_vaccinations.csv"


def ic_text(*school_ids: str) -> str:
    rows = [row for school_id in school_ids for row in expected_ic_rows(school_id)]
    return "".join(f"{row}\n" for row in rows)


def seed_master(world, text: str) -> None:
    """A master committed by an earlier run: the file and its snapshot."""
    world.bucket.write(MASTER, text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    world.bucket.write(f"snapshots/{digest}.csv", text)


def only_drive_file(world) -> tuple[str, str]:
    assert len(world.drive.files) == 1, world.drive.files.keys()
    return next(iter(world.drive.files.items()))


# --- the run cycle ---


def test_first_run_submits_fetches_delivers_and_commits(world, capsys):
    code, result = world.run("run", capsys)

    assert code == 0
    assert result["status"] == "success"
    assert result["new_records"] == len(ic_text("2542", "2543").splitlines())
    assert world.latest_event_types() == [
        "RunStarted",
        "QuerySubmitted",
        "QuerySubmitted",
        "RecordsFetched",
        "RecordsFetched",
        "DiffComputed",
        "Delivered",
        "MasterCommitted",
        "RunCompleted",
    ]
    assert world.aisr.received_uploads == ["2542", "2543"]
    name, text = only_drive_file(world)
    assert name.endswith("_new_vaccinations.csv")
    assert text == ic_text("2542", "2543")
    assert world.bucket.objects[MASTER] == ic_text("2542", "2543")
    diff_event = next(
        e for e in world.latest_run_events() if e["type"] == "DiffComputed"
    )
    assert diff_event["data"]["diff_hash"] == hashlib.sha256(text.encode()).hexdigest()


def test_same_day_rerun_sends_nothing_and_delivers_nothing(world, capsys):
    world.run("run", capsys)
    world.aisr.received_uploads.clear()

    code, result = world.run("run", capsys)

    assert code == 0
    assert (result["status"], result["new_records"]) == ("success", 0)
    assert world.aisr.received_uploads == []
    assert len(world.drive.uploads) == 1
    assert world.latest_event_types() == [
        "RunStarted",
        "RecordsFetched",
        "RecordsFetched",
        "DiffComputed",
        "RunCompleted",
    ]


def test_crash_between_delivery_and_commit_resumes_at_commit(world, capsys):
    # The master write fails after Drive delivery: the run fails loudly
    # with the master untouched; the rerun finds the delivery in the
    # ledger, does not deliver again, finishes the commit, and skips.
    world.bucket.fail_next_write(MASTER, ServiceUnavailable("gcs blip"))

    code, _ = world.run("run", capsys)

    assert code == 1
    assert world.latest_event_types()[-1] == "RunFailed"
    assert world.latest_run_events()[-1]["data"]["step"] == "commit_master"
    assert MASTER not in world.bucket.objects

    code, result = world.run("run", capsys)

    assert code == 0
    assert result["status"] == "skipped"
    assert len(world.drive.uploads) == 1
    assert world.bucket.objects[MASTER] == ic_text("2542", "2543")
    assert world.latest_event_types()[-2:] == ["MasterCommitted", "RunSkipped"]


def test_an_unparseable_master_fails_before_anything_is_delivered(world, capsys):
    seed_master(world, "12345,678901\n")

    code, _ = world.run("run", capsys)

    assert code == 1
    assert world.latest_run_events()[-1]["data"] == {
        "step": "compute_diff",
        "error": "IcFormatError",
    }
    assert world.drive.uploads == []


def test_a_missing_master_with_history_fails_instead_of_flooding(world, capsys):
    world.bucket.write("snapshots/0000.csv", "a,b,c,01/01/2020\n")

    code, _ = world.run("run", capsys)

    assert code == 1
    assert world.latest_run_events()[-1]["data"] == {
        "step": "compute_diff",
        "error": "MasterMissingError",
    }
    assert world.drive.uploads == []
    assert MASTER not in world.bucket.objects


def test_a_miic_format_change_fails_the_run_instead_of_succeeding_empty(world, capsys):
    world.aisr.faults.malformed_results.update({"2542", "2543"})

    code, _ = world.run("run", capsys)

    assert code == 1
    assert world.latest_run_events()[-1]["data"] == {
        "step": "fetch",
        "error": "AllDownloadsFailed",
    }
    assert world.drive.uploads == []


def test_a_stuck_school_delivers_the_rest_then_fails_naming_it(world, capsys):
    period = district_period()
    world.bucket.write(
        f"ledger/claims/{period}_query_2543",
        '{"run_id": "crashed-run", "at": "2026-10-28T07:10:00"}',
    )

    code, result = world.run("run", capsys)

    assert code == 1
    assert result["stuck_schools"] == ["2543"]
    assert world.aisr.received_uploads == ["2542"]
    # 2543's results still listed (an earlier upload), so they still flow.
    _, text = only_drive_file(world)
    assert text == ic_text("2542", "2543")
    assert world.latest_run_events()[-1]["data"] == {
        "step": "submit_queries",
        "error": "QuerySubmissionIncomplete",
        "stuck_schools": ["2543"],
        "failed_schools": [],
    }


def test_a_signing_failure_fails_loudly_then_the_rerun_recovers_alone(world, capsys):
    # Signing failed for 2543: nothing reached MIIC, so its claim is
    # released. The run still delivers, then fails naming 2543; the next
    # run submits 2543 (and only 2543) with no human involved.
    world.aisr.faults.puturl_status["2543"] = 500

    code, result = world.run("run", capsys)

    assert code == 1
    assert result["failed_schools"] == ["2543"]
    assert world.aisr.received_uploads == ["2542"]

    world.aisr.faults.clear()
    world.aisr.received_uploads.clear()
    code, result = world.run("run", capsys)

    assert code == 0
    assert result["status"] == "success"
    assert world.aisr.received_uploads == ["2543"]
    assert len(world.drive.uploads) == 1


def test_the_brake_blocks_a_flood_and_leaves_the_master_alone(world, capsys):
    world.set_schools(["2542", "2544"])
    seed_master(world, ic_text("2542"))

    code, result = world.run("run", capsys)

    assert code == 1
    assert result["status"] == "blocked"
    assert world.latest_run_events()[-1]["data"] == {
        "step": "diff_sanity",
        "error": "SuspiciousDiffVolume",
    }
    assert world.drive.uploads == []
    assert world.bucket.objects[MASTER] == ic_text("2542")


# --- the canary and the rebaseline ---


def test_canary_logs_in_lists_and_reads_the_master(world, capsys):
    seed_master(world, ic_text("2542"))

    code, result = world.run("canary", capsys)

    assert code == 0
    assert result == {
        "status": "success",
        "schools_checked": 2,
        "records_available": 2,
        "known_records": len(expected_ic_rows("2542")),
    }
    assert world.latest_event_types() == ["RunStarted", "RunCompleted"]
    assert world.aisr.received_uploads == []


def test_canary_fails_when_any_listing_fails(world, capsys):
    seed_master(world, ic_text("2542"))
    world.aisr.faults.listing_status["2543"] = 500

    code, _ = world.run("canary", capsys)

    assert code == 1
    assert world.latest_run_events()[-1]["data"] == {
        "step": "canary",
        "error": "StagingCheckFailed",
    }


def test_canary_fails_on_a_missing_master(world, capsys):
    world.bucket.write("snapshots/0000.csv", "a,b,c,01/01/2020\n")

    code, result = world.run("canary", capsys)

    assert code == 1
    assert result["error"] == "MasterMissingError"


def test_rebaseline_pushes_the_whole_master_in_chunks(world, capsys, monkeypatch):
    monkeypatch.setenv("REBASELINE_CHUNK_RECORDS", "4")
    seed_master(world, ic_text("2542"))  # 6 records

    code, result = world.run("rebaseline", capsys)

    assert code == 0
    assert (result["chunks"], result["records"]) == (2, 6)
    names = sorted(world.drive.files)
    assert [n[10:] for n in names] == [
        "_rebaseline_01-of-02.csv",
        "_rebaseline_02-of-02.csv",
    ]
    assert "".join(world.drive.files[n] for n in names) == ic_text("2542")
    assert world.latest_event_types() == [
        "RunStarted",
        "Delivered",
        "Delivered",
        "RunCompleted",
    ]


# --- the PHI scan itself ---


def test_the_phi_scan_catches_a_planted_leak():
    from tests.e2e.conftest import find_leaks
    from tests.fakes import FakeBucket

    bucket = FakeBucket()
    bucket.write("ledger/2026/10/run-x/001_RunFailed.json", '{"error": "8100231"}')
    bucket.write(
        "output/all_known_vaccinations.csv", "8100231,9100231,MMR,01/01/2019\n"
    )

    leaks = find_leaks("INFO parsed Zelda Canaryfield", ["{}"], bucket)

    # Logs and ledger are scanned; the master (the data path) is not.
    assert ("logs", "Zelda") in leaks
    assert ("ledger", "8100231") in leaks
    assert all(surface != "master" for surface, _ in leaks)
    assert not find_leaks("INFO 2/2 schools staged", [], FakeBucket())
