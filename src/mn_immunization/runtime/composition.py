"""The composition root: the one place adapters are constructed.

Everything district-specific and everything that touches GCP, Drive, or
AISR is wired here from Settings; the pipeline receives the result as
ports (`pipeline.services.Services`) and never names an implementation.
`tests/test_architecture.py` holds the line.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from mn_immunization.gcp.secrets import secret_reader
from mn_immunization.gcp.storage import GcsObjectStore, get_storage_client
from mn_immunization.ledger.gcs_ledger import GcsRunLedger, GcsSnapshotStore
from mn_immunization.pipeline.services import Clock, Services
from mn_immunization.pipeline.settings import Settings
from mn_immunization.sinks.drive import GoogleDriveSink
from mn_immunization.sources.aisr.client import aisr_opener

SYSTEM_CLOCK = Clock(
    now=lambda: datetime.now(UTC), sleep=time.sleep, monotonic=time.monotonic
)


def build_services(settings: Settings, clock: Clock = SYSTEM_CLOCK) -> Services:
    """Production wiring for one district: its bucket, its secrets, its
    Drive folder, and AISR."""
    bucket = get_storage_client().bucket(settings.data_bucket)
    secret = secret_reader(settings.gcp_project)
    folder = settings.drive_folder_id
    return Services(
        settings=settings,
        clock=clock,
        new_ledger=lambda run_id: GcsRunLedger(bucket, run_id, now=clock.now),
        snapshots=GcsSnapshotStore(bucket),
        objects=GcsObjectStore(bucket),
        drive=GoogleDriveSink(folder, secret) if folder else None,
        open_source=aisr_opener(secret),
    )
