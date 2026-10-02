"""Periods: the unit of work that spans executions.

`run` opens a period (one roster submission per school, so one nurse
email each); `tick` executions advance whichever period is open until it
closes. Whether a period is open is a fold over the ledger, never memory:
its latest PeriodOpened is later than its latest PeriodClosed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class OpenPeriod:
    key: str
    opened_at: datetime  # UTC; the staging deadline counts from here


def period_key(local_now: datetime, period_format: str) -> str:
    """The period a submission made now belongs to (QUERY_PERIOD_FORMAT of
    the district-local time): "%Y-%m" monthly, "%Y-%m-%d" per run day."""
    return local_now.strftime(period_format)


def open_periods(runs: list[dict]) -> list[OpenPeriod]:
    """Periods opened and not since closed, most recently opened first.

    Events are ordered by their UTC stamp, then by when their run started,
    then by sequence, so a close and a reopen in the same second still
    fold in the order they happened."""
    stamped = []
    for run in runs:
        started = run["events"][0]["at"] if run["events"] else ""
        for event in run["events"]:
            if event["type"] in ("PeriodOpened", "PeriodClosed"):
                stamped.append(((event["at"], started, event["seq"]), event))
    state: dict[str, OpenPeriod | None] = {}
    for _, event in sorted(stamped, key=lambda pair: pair[0]):
        key = event["data"]["period"]
        if event["type"] == "PeriodOpened":
            opened = datetime.fromisoformat(event["at"]).replace(tzinfo=UTC)
            state[key] = OpenPeriod(key=key, opened_at=opened)
        else:
            state[key] = None
    still_open = [period for period in state.values() if period is not None]
    return sorted(still_open, key=lambda p: p.opened_at, reverse=True)
