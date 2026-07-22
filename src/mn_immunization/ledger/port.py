"""Ports for the run ledger and snapshot store.

GCS adapters are today's implementations. If a frontend ever needs to query
the ledger, a Firestore adapter implements RunLedger and slots in here.
"""

from __future__ import annotations

from typing import Protocol

from mn_immunization.ledger.events import LedgerEvent


class RunLedger(Protocol):
    def append(self, event: LedgerEvent) -> None: ...

    def claim(self, key: str) -> bool:
        """Atomically claim a key. True exactly once per key, across runs."""
        ...


class SnapshotStore(Protocol):
    def put(self, content: str) -> tuple[str, str]:
        """Store content-addressed; returns (sha256_hex, storage_path)."""
        ...
