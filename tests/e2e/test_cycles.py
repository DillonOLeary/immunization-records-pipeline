"""Characterization of every cycle, end to end, through the job entrypoint.

Each scenario pins what a run does to the outside world: the ledger events
it writes (exact sequence), what lands in Drive (exact text), what happens
to the known set, which rosters reach MIIC, and the exit code the alert
keys on. The autouse PHI scan (conftest) runs on every one of them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from google.api_core.exceptions import ServiceUnavailable
from minnesota_immunization_mock.sample_data import expected_ic_rows

from mn_immunization.workflow.layout import KNOWN_MARKER, KNOWN_RECORDS
from tests.fakes import district_period

MASTER = KNOWN_RECORDS


def ic_text(*school_ids: str) -> str:
    rows = [row for school_id in school_ids for row in expected_ic_rows(school_id)]
    return "".join(f"{row}\n" for row in rows)


def seed_master(world, text: str) -> None:
    """A known set committed by an earlier run: the records and the marker."""
    world.bucket.write(MASTER, text)
    world.bucket.write(KNOWN_MARKER, '{"records": 1}')


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
        "PeriodOpened",
        "QuerySubmitted",
        "QuerySubmitted",
        "RecordsFetched",
        "RecordsFetched",
        "DiffComputed",
        "Delivered",
        "MasterCommitted",
        "PeriodClosed",
        "RunCompleted",
    ]
    assert world.aisr.received_uploads == ["2542", "2543"]
    name, text = only_drive_file(world)
    assert name.endswith("_new_01-of-01.csv")
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
        "PeriodOpened",
        "RecordsFetched",
        "RecordsFetched",
        "DiffComputed",
        "PeriodClosed",
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
    assert world.latest_event_types()[-3:] == [
        "MasterCommitted",
        "PeriodClosed",
        "RunSkipped",
    ]


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
    world.bucket.write(KNOWN_MARKER, '{"records": 1}')

    code, _ = world.run("run", capsys)

    assert code == 1
    assert world.latest_run_events()[-1]["data"] == {
        "step": "compute_diff",
        "error": "KnownRecordsMissingError",
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


def test_last_periods_results_still_listed_are_not_mistaken_for_this_periods(
    world, capsys
):
    # 2026-10-01 in production: right after the uploads, AISR still listed
    # September's results, the probe counted them as staged, and the run
    # fetched stale files. Results older than this period's submission
    # must not count; the run waits (here: until its zero deadline) and
    # fails loudly instead of quietly processing last period's data.
    world.aisr.faults.stale_listing.update({"2542", "2543"})

    code, _ = world.run("run", capsys)

    assert code == 1
    assert world.latest_run_events()[-1]["data"]["error"] == "NoResultsStaged"
    assert "RecordsFetched" not in world.latest_event_types()
    assert world.drive.uploads == []

    # Once the fresh results are listed, a rerun sends nothing to MIIC and
    # processes them.
    world.aisr.faults.clear()
    world.aisr.received_uploads.clear()
    code, result = world.run("run", capsys)

    assert code == 0
    assert result["status"] == "success"
    assert world.aisr.received_uploads == []
    assert len(world.drive.uploads) == 1


def test_a_second_run_the_same_day_with_new_records_delivers_them(world, capsys):
    # 2026-10-01: a same-day second diff used to look "already delivered"
    # (date claim, same file name) and its records would have been
    # committed without reaching staff. Now it gets its own file.
    world.set_schools(["2542"])
    world.run("run", capsys)
    world.set_schools(["2542", "2543"])

    code, result = world.run("run", capsys)

    assert code == 0
    assert result["new_records"] == len(expected_ic_rows("2543"))
    first, second = world.drive.uploads
    assert first != second
    assert first.endswith("_new_01-of-01.csv") and second.endswith("_new_01-of-01.csv")
    assert world.drive.files[first] == ic_text("2542")
    assert world.drive.files[second] == ic_text("2543")
    assert world.bucket.objects[MASTER] == ic_text("2542", "2543")


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


# --- periods across executions: run opens, ticks advance ---


def test_a_tick_with_no_open_period_writes_nothing(world, capsys):
    code = world.tick(capsys)

    assert code == 0
    assert world.printed[-1] == '{"status": "idle"}'
    assert world.bucket.objects.keys() == {
        "config/config.json",
        "rosters/2542.csv",
        "rosters/2543.csv",
    }


def test_a_period_waits_across_ticks_until_results_stage(world, capsys, monkeypatch):
    # MDH takes hours to stage results. `run` submits and ends "waiting"
    # with the period open; ticks look again without sleeping or
    # resubmitting; once results are in, a tick delivers and closes the
    # period, and later ticks are idle.
    monkeypatch.setenv("POLL_DEADLINE_SECONDS", "72000")
    world.aisr.faults.stale_listing.update({"2542", "2543"})

    code, result = world.run("run", capsys)

    assert (code, result["status"]) == (0, "waiting")
    assert result["reason"] == "0/2 schools have results staged"
    assert world.aisr.received_uploads == ["2542", "2543"]
    assert world.latest_event_types()[-1] == "RunWaiting"

    code, result = world.run("tick", capsys)
    assert (code, result["status"]) == (0, "waiting")

    world.aisr.faults.clear()
    code, result = world.run("tick", capsys)

    assert (code, result["status"]) == (0, "success")
    assert world.aisr.received_uploads == ["2542", "2543"]
    _, text = only_drive_file(world)
    assert text == ic_text("2542", "2543")
    assert world.latest_event_types()[-2:] == ["PeriodClosed", "RunCompleted"]

    assert world.tick(capsys) == 0
    assert world.printed[-1] == '{"status": "idle"}'


def test_a_failed_period_is_retried_by_running_again(world, capsys):
    # Every failure closes the period (one alert, no repeats every tick);
    # `run` reopens it without resending a roster.
    world.aisr.faults.stale_listing.update({"2542", "2543"})
    code, _ = world.run("run", capsys)
    assert code == 1
    assert world.tick(capsys) == 0  # closed: the tick is idle

    world.aisr.faults.clear()
    world.aisr.received_uploads.clear()
    code, result = world.run("run", capsys)

    assert (code, result["status"]) == (0, "success")
    assert world.aisr.received_uploads == []


def test_a_failure_outside_the_steps_also_closes_the_period(world, capsys, monkeypatch):
    # An unreadable config fails the tick before any step runs; the period
    # closes like any other failure, so the next tick is idle instead of
    # failing (and alerting) again.
    monkeypatch.setenv("POLL_DEADLINE_SECONDS", "72000")
    world.aisr.faults.stale_listing.update({"2542", "2543"})
    world.run("run", capsys)
    del world.bucket.objects["config/config.json"]

    code, result = world.run("tick", capsys)

    assert (code, result["error"]) == (1, "ObjectNotFoundError")
    assert world.latest_event_types()[-2:] == ["PeriodClosed", "RunFailed"]
    assert world.tick(capsys) == 0
    assert world.printed[-1] == '{"status": "idle"}'


def test_opening_a_period_supersedes_one_left_open(world, capsys):
    now = datetime.now(UTC).replace(tzinfo=None)
    world.bucket.write(
        f"ledger/{now:%Y}/{now:%m}/run_old/001_PeriodOpened.json",
        json.dumps(
            {
                "run_id": "run_old",
                "seq": 1,
                "type": "PeriodOpened",
                "at": now.isoformat(timespec="seconds"),
                "data": {"period": "1999-01"},
            }
        ),
    )

    code, _ = world.run("run", capsys)

    assert code == 0
    closed = [e for e in world.latest_run_events() if e["type"] == "PeriodClosed"]
    assert [e["data"] for e in closed] == [
        {"period": "1999-01", "outcome": "superseded"},
        {"period": district_period(), "outcome": "success"},
    ]


# --- the canary and the rebaseline ---


def test_canary_logs_in_lists_and_reads_the_master(world, capsys, caplog):
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
    assert f"District zone America/Chicago: roster period {district_period()}" in (
        caplog.text
    )


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
    world.bucket.write(KNOWN_MARKER, '{"records": 1}')

    code, result = world.run("canary", capsys)

    assert code == 1
    assert result["error"] == "KnownRecordsMissingError"


def test_refresh_rebuilds_the_known_set_and_delivers_all_of_it(
    world, capsys, monkeypatch
):
    # No roster goes out (no one is emailed); every record MIIC lists is
    # delivered as capped files, and the known set becomes exactly that.
    monkeypatch.setenv("DELIVERY_FILE_ROWS", "4")
    seed_master(world, "1,2,MMR,01/01/2001\n")  # stale: refresh replaces it

    code, result = world.run("refresh", capsys)

    assert code == 0
    assert (result["files"], result["records"]) == (3, 10)
    assert world.aisr.received_uploads == []
    names = sorted(world.drive.files)
    assert [n[15:] for n in names] == [  # after YYYY-MM-DD_HHMM
        "_refresh_01-of-03.csv",
        "_refresh_02-of-03.csv",
        "_refresh_03-of-03.csv",
    ]
    delivered = "".join(world.drive.files[n] for n in names)
    assert sorted(delivered.splitlines()) == sorted(
        ic_text("2542", "2543").splitlines()
    )
    assert sorted(world.bucket.objects[MASTER].splitlines()) == sorted(
        ic_text("2542", "2543").splitlines()
    )
    assert world.latest_event_types()[-2:] == ["MasterCommitted", "RunCompleted"]


def test_refresh_is_all_or_nothing(world, capsys):
    seed_master(world, ic_text("2542"))
    world.aisr.faults.listing_status["2543"] = 500

    code, result = world.run("refresh", capsys)

    assert code == 1
    assert world.drive.uploads == []
    assert world.bucket.objects[MASTER] == ic_text("2542")


def test_a_delivery_cut_short_is_finished_by_the_rerun(world, capsys, monkeypatch):
    # Drive fails on the second of three files: the run fails with the
    # known set untouched; the rerun sends only the missing parts, under
    # the first run's names, then commits.
    monkeypatch.setenv("DELIVERY_FILE_ROWS", "4")
    world.drive.fail_upload_after = 1

    code, _ = world.run("run", capsys)

    assert code == 1
    assert len(world.drive.uploads) == 1
    assert MASTER not in world.bucket.objects

    world.drive.fail_upload_after = None
    code, _ = world.run("run", capsys)

    assert code == 0
    first, *rest = world.drive.uploads
    assert first.endswith("_01-of-03.csv")
    assert [n.removeprefix(first[:20]) for n in rest] == [  # YYYY-MM-DD_HHMM_new_
        "02-of-03.csv",
        "03-of-03.csv",
    ]
    assert sorted(world.bucket.objects[MASTER].splitlines()) == sorted(
        ic_text("2542", "2543").splitlines()
    )


# --- the PHI scan itself ---


def test_the_phi_scan_catches_a_planted_leak():
    from tests.e2e.conftest import find_leaks
    from tests.fakes import FakeBucket

    bucket = FakeBucket()
    bucket.write("ledger/2026/10/run-x/001_RunFailed.json", '{"error": "8100231"}')
    bucket.write(KNOWN_RECORDS, "8100231,9100231,MMR,01/01/2019\n")

    leaks = find_leaks("INFO parsed Zelda Canaryfield", ["{}"], bucket)

    # Logs and ledger are scanned; the master (the data path) is not.
    assert ("logs", "Zelda") in leaks
    assert ("ledger", "8100231") in leaks
    assert all(surface != "master" for surface, _ in leaks)
    assert not find_leaks("INFO 2/2 schools staged", [], FakeBucket())
