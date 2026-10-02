"""RunContext: one cycle's view of the world, as ports.

Built by `cycles.pipeline_run` from Services plus what this run loaded
(its ledger, schools, temp dir) and the period it works on. The
workflow never sees an adapter class, an endpoint, a bucket, a credential, the
environment, or the system clock. Tests build one from fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mn_immunization.workflow.ports import (
    Delivery,
    ObjectStore,
    RegistryOpener,
    RunLedger,
    School,
    SnapshotStore,
)
from mn_immunization.workflow.services import Clock
from mn_immunization.workflow.settings import Settings


@dataclass
class RunContext:
    settings: Settings
    clock: Clock
    ledger: RunLedger
    snapshots: SnapshotStore
    objects: ObjectStore
    delivery: Delivery | None  # None: no delivery folder configured
    open_registry: RegistryOpener
    temp: Path
    period: str  # the period this execution works on (periods.period_key)
    opened_at: datetime  # when that period was (re)opened, UTC
    schools: list[School] = field(default_factory=list)

    def local_now(self) -> datetime:
        """Now in the district's zone: roster periods and delivery dates
        follow the district's calendar, as its schedulers do. (Ledger
        timestamps and run ids stay UTC.)"""
        return self.clock.now().astimezone(self.settings.time_zone)
