"""Whether a period is open is a fold over the ledger, never memory."""

from datetime import UTC, datetime

from mn_immunization.workflow.periods import OpenPeriod, open_periods, period_key


def run(run_id: str, *events: tuple[str, str, str]) -> dict:
    """A run's stored events: (type, period, at) each, after RunStarted."""
    started = events[0][2] if events else "2026-10-01T00:00:00"
    stored = [{"type": "RunStarted", "seq": 1, "at": started, "data": {}}]
    for seq, (kind, period, at) in enumerate(events, start=2):
        stored.append({"type": kind, "seq": seq, "at": at, "data": {"period": period}})
    return {"run_id": run_id, "events": stored}


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_no_periods_without_events():
    assert open_periods([run("r1")]) == []


def test_an_opened_period_is_open_from_when_it_opened():
    runs = [run("r1", ("PeriodOpened", "2026-10", "2026-10-28T07:09:00"))]
    assert open_periods(runs) == [OpenPeriod("2026-10", utc("2026-10-28T07:09:00"))]


def test_a_closed_period_is_not_open():
    runs = [
        run("r2", ("PeriodClosed", "2026-10", "2026-10-28T13:17:00")),
        run("r1", ("PeriodOpened", "2026-10", "2026-10-28T07:09:00")),
    ]
    assert open_periods(runs) == []


def test_a_reopened_period_counts_from_the_reopening():
    runs = [
        run("r3", ("PeriodOpened", "2026-10", "2026-10-30T09:00:00")),
        run(
            "r1",
            ("PeriodOpened", "2026-10", "2026-10-28T07:09:00"),
            ("PeriodClosed", "2026-10", "2026-10-28T07:20:00"),
        ),
    ]
    assert open_periods(runs) == [OpenPeriod("2026-10", utc("2026-10-30T09:00:00"))]


def test_a_reopening_in_the_same_second_as_a_close_still_reopens():
    # Ledger stamps have one-second resolution; the later run wins a tie.
    runs = [
        run("r2", ("PeriodOpened", "2026-10", "2026-10-28T07:20:00")),
        {
            "run_id": "r1",
            "events": [
                {"type": "RunStarted", "seq": 1, "at": "2026-10-28T07:09:00"},
                {
                    "type": "PeriodClosed",
                    "seq": 9,
                    "at": "2026-10-28T07:20:00",
                    "data": {"period": "2026-10"},
                },
            ],
        },
    ]
    assert [p.key for p in open_periods(runs)] == ["2026-10"]


def test_several_open_periods_come_newest_first():
    runs = [
        run("r1", ("PeriodOpened", "2026-10-26", "2026-10-26T07:00:00")),
        run("r2", ("PeriodOpened", "2026-10-29", "2026-10-29T07:00:00")),
    ]
    assert [p.key for p in open_periods(runs)] == ["2026-10-29", "2026-10-26"]


def test_the_period_key_is_the_format_of_local_time():
    local = datetime(2026, 9, 30, 22, 0)
    assert period_key(local, "%Y-%m") == "2026-09"
    assert period_key(local, "%Y-%m-%d") == "2026-09-30"
