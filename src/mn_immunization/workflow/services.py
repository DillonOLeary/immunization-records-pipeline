"""What a cycle is given: settings, the clock, and every adapter as a port.

`runtime/composition.py` builds the production Services; tests build
theirs from fakes. Nothing in the workflow constructs an adapter, reads the
environment, or reads the clock itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from mn_immunization.workflow.ports import (
    Delivery,
    District,
    ObjectStore,
    RunLedger,
)
from mn_immunization.workflow.settings import Settings


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
    objects: ObjectStore
    delivery: Delivery | None  # None: no delivery folder configured
    # Reads the district's config and binds its adapters: called inside
    # each cycle, so a bad config is a recorded RunFailed like any other.
    load_district: Callable[[], District]
