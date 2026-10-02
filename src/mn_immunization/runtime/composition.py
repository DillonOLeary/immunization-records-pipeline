"""The composition root: the one place adapters are constructed.

Everything district-specific and everything that touches GCP, Drive, or
AISR is wired here from Settings and the district's config; the
workflow receives the result as ports (`workflow.services.Services`) and
never names an implementation. `tests/test_architecture.py` holds the line.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from mn_immunization.adapters.drive.delivery import GoogleDriveDelivery
from mn_immunization.adapters.gcs.ledger import GcsRunLedger
from mn_immunization.adapters.gcs.secrets import secret_reader
from mn_immunization.adapters.gcs.storage import GcsObjectStore, get_storage_client
from mn_immunization.runtime.config import CONFIG_PATH, district_from_config
from mn_immunization.workflow.services import Clock, Services
from mn_immunization.workflow.settings import Settings

SYSTEM_CLOCK = Clock(now=lambda: datetime.now(UTC))


def build_services(settings: Settings, clock: Clock = SYSTEM_CLOCK) -> Services:
    """Production wiring for one district: its bucket, its secrets, its
    Drive folder, and (from its config, read inside each cycle) AISR."""
    bucket = get_storage_client().bucket(settings.data_bucket)
    secret = secret_reader(settings.gcp_project)
    folder = settings.drive_folder_id
    objects = GcsObjectStore(bucket)
    return Services(
        settings=settings,
        clock=clock,
        new_ledger=lambda run_id: GcsRunLedger(bucket, run_id, now=clock.now),
        objects=objects,
        delivery=GoogleDriveDelivery(folder, secret) if folder else None,
        load_district=lambda: district_from_config(
            json.loads(objects.read_text(CONFIG_PATH)), secret
        ),
    )
