"""RunContext: one cycle's view of the world, as ports.

Built by `cycles.pipeline_run` from Services plus what this run loaded
(its ledger, config, schools, temp dir). The pipeline never sees an
adapter class, a bucket, a credential, the environment, or the system
clock. Tests build one from fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mn_immunization.gcp.port import ObjectStore
from mn_immunization.ledger.port import RunLedger, SnapshotStore
from mn_immunization.pipeline.services import Clock
from mn_immunization.pipeline.settings import Settings
from mn_immunization.sinks.port import DriveSink
from mn_immunization.sources.aisr.port import (
    DistrictInfo,
    SchoolQueryInformation,
    SourceOpener,
)


@dataclass
class RunContext:
    settings: Settings
    clock: Clock
    ledger: RunLedger
    snapshots: SnapshotStore
    objects: ObjectStore
    drive: DriveSink | None  # None: no delivery folder configured
    open_source: SourceOpener
    temp: Path
    auth_url: str
    api_url: str
    district: DistrictInfo
    schools: list[SchoolQueryInformation] = field(default_factory=list)

    def local_now(self) -> datetime:
        """Now in the district's zone: roster periods and delivery dates
        follow the district's calendar, as its schedulers do. (Ledger
        timestamps and run ids stay UTC.)"""
        return self.clock.now().astimezone(self.settings.time_zone)
