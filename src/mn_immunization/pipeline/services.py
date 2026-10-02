"""What a cycle is given: settings, the clock, and every adapter as a port.

`runtime/composition.py` builds the production Services; tests build
theirs from fakes. Nothing in the pipeline constructs an adapter, reads
the environment, or reads the clock itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from mn_immunization.gcp.port import ObjectStore
from mn_immunization.ledger.port import RunLedger, SnapshotStore
from mn_immunization.pipeline.settings import Settings
from mn_immunization.sinks.port import DriveSink
from mn_immunization.sources.aisr.port import SourceOpener


@dataclass(frozen=True)
class Clock:
    """Wall time (timezone-aware, UTC) for periods, dates, deadlines, and
    ledger stamps. Nothing sleeps: a wait ends the execution, and the
    next tick looks again."""

    now: Callable[[], datetime]


@dataclass(frozen=True)
class Services:
    settings: Settings
    clock: Clock
    new_ledger: Callable[[str], RunLedger]  # run id -> that run's ledger
    snapshots: SnapshotStore
    objects: ObjectStore
    drive: DriveSink | None  # None: no delivery folder configured
    open_source: SourceOpener
