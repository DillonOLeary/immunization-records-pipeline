"""In-memory ledger and snapshot store.

Used by tests, and by local CLI runs that have no bucket: the pipeline
always has a ledger to write to, and the terminal-event guarantee holds
everywhere.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime

from mn_immunization.ledger.events import LedgerEvent


class InMemoryRunLedger:
    """`history` is earlier runs' event envelopes, as recent_runs would
    read them from storage; `claims` maps each held key to its payload."""

    def __init__(
        self,
        run_id: str = "test-run",
        now: Callable[[], datetime] = datetime.now,
        history: list[dict] | None = None,
    ) -> None:
        self.run_id = run_id
        self._now = now
        self.events: list[dict] = []
        self.history: list[dict] = list(history or [])
        self.claims: dict[str, dict] = {}

    def append(self, event: LedgerEvent) -> None:
        self.events.append(
            {
                "run_id": self.run_id,
                "seq": len(self.events) + 1,
                "type": event.type,
                "at": self._now().isoformat(timespec="seconds"),
                "data": event.data,
            }
        )

    def claim(self, key: str) -> bool:
        if key in self.claims:
            return False
        self.claims[key] = {
            "run_id": self.run_id,
            "at": self._now().isoformat(timespec="seconds"),
        }
        return True

    def recent_runs(self, months: int = 2, limit: int | None = None) -> list[dict]:
        by_run: dict[str, list[dict]] = {}
        for event in [*self.history, *self.events]:
            by_run.setdefault(event["run_id"], []).append(event)
        runs = [
            {"run_id": run_id, "events": sorted(evs, key=lambda e: e["seq"])}
            for run_id, evs in by_run.items()
        ]
        runs.sort(key=lambda r: r["events"][0]["at"], reverse=True)
        return runs if limit is None else runs[:limit]

    def held_claims(self, prefix: str) -> dict[str, dict]:
        return {k: v for k, v in self.claims.items() if k.startswith(prefix)}

    def event_types(self) -> list[str]:
        return [event["type"] for event in self.events]


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, str] = {}

    def put(self, content: str) -> tuple[str, str]:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = f"snapshots/{digest}.csv"
        self.snapshots[path] = content
        return digest, path

    def any_stored(self) -> bool:
        return bool(self.snapshots)
