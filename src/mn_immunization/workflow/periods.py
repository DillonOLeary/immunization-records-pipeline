"""Periods: the unit of work that spans executions.

`run` opens a period (one roster submission per school, so one nurse
email each); `tick` executions advance whichever period is open until it
closes. Whether a period is open is a fold over the ledger, never memory
(`history.History.open_periods`): its latest PeriodOpened is later than
its latest PeriodClosed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OpenPeriod:
    key: str
    opened_at: datetime  # UTC; the staging deadline counts from here


def period_key(local_now: datetime, period_format: str) -> str:
    """The period a submission made now belongs to (QUERY_PERIOD_FORMAT of
    the district-local time): "%Y-%m" monthly, "%Y-%m-%d" per run day."""
    return local_now.strftime(period_format)
