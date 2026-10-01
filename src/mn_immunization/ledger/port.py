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

    def recent_runs(self, months: int = 2, limit: int | None = None) -> list[dict]:
        """Recent runs (this run included), newest first: dicts of run_id
        and events, each event the stored envelope (type, data, at, ...)."""
        ...

    def held_claims(self, prefix: str) -> dict[str, dict]:
        """Claims whose key starts with prefix: key -> claimant payload."""
        ...


class SnapshotStore(Protocol):
    def put(self, content: str) -> tuple[str, str]:
        """Store content-addressed; returns (sha256_hex, storage_path)."""
        ...

    def any_stored(self) -> bool:
        """Has any snapshot ever been stored? Every master commit stores
        one, so True means a master was committed before: an absent or
        empty master is then damage, not a first run."""
        ...
