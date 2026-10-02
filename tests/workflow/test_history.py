"""History: the ledger's events folded into what the workflow needs to
know about the past. Whether a period is open, which schools went out,
what was delivered and imported: folds over the ledger, never memory."""

from datetime import UTC, datetime

from mn_immunization.workflow.history import History
from mn_immunization.workflow.periods import OpenPeriod, period_key


def run(run_id: str, *events: tuple) -> dict:
    """A run's stored events after RunStarted: (type, period, at), or
    (type, data, at) for data beyond a period."""
    started = events[0][2] if events else "2026-10-01T00:00:00"
    stored = [{"type": "RunStarted", "seq": 1, "at": started, "data": {}}]
    for seq, (kind, data, at) in enumerate(events, start=2):
        data = data if isinstance(data, dict) else {"period": data}
        stored.append({"type": kind, "seq": seq, "at": at, "data": data})
    return {"run_id": run_id, "events": stored}


def open_periods(runs):
    return History.from_runs(runs).open_periods()


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


def test_submissions_are_per_period_with_the_latest_time():
    runs = [
        run(
            "r1",
            (
                "QuerySubmitted",
                {"school_id": "2542", "period": "2026-10"},
                "2026-10-01T21:24:40",
            ),
            (
                "QuerySubmitted",
                {"school_id": "2543", "period": "2026-09"},
                "2026-10-01T21:24:41",
            ),
            ("QuerySubmitted", {"school_id": "2544"}, "2026-10-01T21:24:42"),
        ),
        run(
            "r2",
            (
                "QuerySubmitted",
                {"school_id": "2542", "period": "2026-10"},
                "2026-10-02T08:00:00",
            ),
        ),
    ]
    history = History.from_runs(runs)

    # 2544 predates per-school periods and counts for none
    assert history.submissions("2026-10") == {"2542": utc("2026-10-02T08:00:00")}
    assert set(history.submissions("2026-09")) == {"2543"}


def test_deliveries_and_confirmed_imports():
    runs = [
        run(
            "r1",
            (
                "Delivered",
                {"file_name": "a.csv", "target": "drive", "content_hash": "h1"},
                "2026-10-01T21:30:00",
            ),
            (
                "Delivered",
                {"file_name": "old.csv", "target": "drive"},
                "2026-10-01T21:30:01",
            ),
            (
                "Delivered",
                {"file_name": "x.csv", "target": "elsewhere"},
                "2026-10-01T21:30:02",
            ),
            (
                "ImportConfirmed",
                {"file_name": "old.csv", "how": "deleted"},
                "2026-10-01T21:30:03",
            ),
        )
    ]
    history = History.from_runs(runs)

    assert history.deliveries() == {"a.csv": "h1", "old.csv": ""}
    assert history.confirmed_imports() == {"old.csv"}


def test_periods_named_by_openings_and_submissions():
    runs = [
        run(
            "r1",
            ("PeriodOpened", "2026-10-26", "2026-10-26T07:00:00"),
            (
                "QuerySubmitted",
                {"school_id": "2542", "period": "2026-10-29"},
                "2026-10-29T07:00:00",
            ),
            ("QuerySubmitted", {"school_id": "2543"}, "2026-10-29T07:00:01"),
        )
    ]
    assert History.from_runs(runs).periods() == {"2026-10-26", "2026-10-29"}
