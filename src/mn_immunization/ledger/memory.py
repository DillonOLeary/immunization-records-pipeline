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
    def __init__(
        self, run_id: str = "test-run", now: Callable[[], datetime] = datetime.now
    ) -> None:
        self.run_id = run_id
        self._now = now
        self.events: list[dict] = []
        self.claims: set[str] = set()

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
        self.claims.add(key)
        return True

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
