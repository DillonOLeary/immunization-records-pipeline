"""History: the ledger's recent events, folded into what the workflow
needs to know about the past.

The ledger is append-only JSON envelopes. Every question the workflow
asks of it is a fold over them, and they all live here, over typed
entries in the order things happened:
- is a period open?
- which schools were submitted this period, and when?
- what was delivered, and was it imported?

That replaces each step scanning raw dicts by type-name string. Pure:
built from what `RunLedger.recent_runs` returns.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mn_immunization.workflow import events
from mn_immunization.workflow.periods import OpenPeriod


@dataclass(frozen=True)
class Entry:
    """One stored event. `order` is (UTC stamp, its run's first stamp,
    sequence): stamps have one-second resolution, and a later run wins a
    tie, so a close and a reopen in the same second fold correctly."""

    type: str
    data: Mapping[str, Any]
    at: datetime  # UTC
    order: tuple[str, str, int]


class History:
    def __init__(self, entries: list[Entry]):
        self.entries = sorted(entries, key=lambda entry: entry.order)

    @classmethod
    def from_runs(cls, runs: list[dict]) -> History:
        entries = []
        for run in runs:
            started = run["events"][0]["at"] if run["events"] else ""
            for event in run["events"]:
                entries.append(
                    Entry(
                        type=event["type"],
                        data=event.get("data", {}),
                        at=datetime.fromisoformat(event["at"]).replace(tzinfo=UTC),
                        order=(event["at"], started, event["seq"]),
                    )
                )
        return cls(entries)

    def _of(self, *types: str) -> list[Entry]:
        return [entry for entry in self.entries if entry.type in types]

    def open_periods(self) -> list[OpenPeriod]:
        """Periods opened and not since closed, most recently opened first."""
        state: dict[str, OpenPeriod | None] = {}
        for entry in self._of(events.PERIOD_OPENED, events.PERIOD_CLOSED):
            key = entry.data["period"]
            opened = entry.type == events.PERIOD_OPENED
            state[key] = OpenPeriod(key, entry.at) if opened else None
        still_open = [period for period in state.values() if period is not None]
        return sorted(still_open, key=lambda p: p.opened_at, reverse=True)

    def submissions(self, period: str) -> dict[str, datetime]:
        """School id -> when its roster last went out for `period` (UTC).
        Events written before per-school claims carry no period and are
        ignored."""
        times: dict[str, datetime] = {}
        for entry in self._of(events.QUERY_SUBMITTED):
            if entry.data.get("period") == period:
                school_id = entry.data["school_id"]
                times[school_id] = max(entry.at, times.get(school_id, entry.at))
        return times

    def deliveries(self) -> dict[str, str]:
        """Drive file name -> its content hash ("" for deliveries recorded
        before hashes were)."""
        return {
            entry.data["file_name"]: entry.data.get("content_hash", "")
            for entry in self._of(events.DELIVERED)
            if entry.data.get("target") == "drive"
        }

    def confirmed_imports(self) -> set[str]:
        """Delivered files already recorded as imported."""
        return {entry.data["file_name"] for entry in self._of(events.IMPORT_CONFIRMED)}

    def periods(self) -> set[str]:
        """Every period an opening or a submission names."""
        return {
            entry.data["period"]
            for entry in self._of(events.PERIOD_OPENED, events.QUERY_SUBMITTED)
            if "period" in entry.data
        }
