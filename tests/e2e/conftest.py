"""End-to-end harness: the real job entrypoint, end to end, against fakes.

Every test here runs `job.main([...])`, which runs the real cycles, the
real decider and executors, the real AISR adapter (against the in-process
fake AISR), and the real GCS ledger and known-set code over one
shared FakeBucket. Only the edges are swapped, by handing `job.main` a
`build` that composes test services: the bucket, Secret Manager, and Drive.

Two guarantees ride along on every test that uses `world`:

- **No PHI leaves the data path.** Every log record (all loggers, DEBUG
  and up), everything printed, and every ledger object is scanned for
  each value in the fake AISR's CANARY_PHI. The master, diff, and Drive
  files legitimately hold records and are not scanned.
- Nothing reaches real GCP: there is no patching at all; the services
  simply contain no real cloud adapter.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from minnesota_immunization_mock.sample_data import CANARY_PHI

import mn_immunization.runtime.job as job
from mn_immunization.adapters.gcs.ledger import (
    GcsRunLedger,
    read_recent_runs,
    recent_months,
)
from mn_immunization.adapters.gcs.storage import GcsObjectStore
from mn_immunization.runtime.config import CONFIG_PATH, district_from_config
from mn_immunization.workflow.layout import roster_path
from mn_immunization.workflow.services import Clock, Services
from mn_immunization.workflow.settings import Settings
from tests.conftest import MockAisr
from tests.fakes import FakeBucket, FakeDrive

BUCKET = "e2e-bucket"
SCHOOLS = {"2542": "Friendly Hills Mid", "2543": "Garlough Elementary"}
SECRETS = {
    "miic-username": "test_user",
    "miic-password": "test_password",
    "drive-refresh-token": "fake-refresh",
    "drive-client-id": "fake-client",
    "drive-client-secret": "fake-secret",
    "infinite-campus-username": "ic_user",
    "infinite-campus-password": "ic_password",
}
IC_CALENDARS = {"2542": "FHMS", "2543": "GEMS", "2544": "PK"}


@dataclass
class World:
    bucket: FakeBucket
    drive: FakeDrive
    aisr: MockAisr
    printed: list[str] = field(default_factory=list)
    last_run_id: str = ""

    def set_schools(self, school_ids: list[str], ic: bool = False) -> None:
        """Write config.json and a roster per school into the bucket; with
        `ic`, rosters are to be exported from the fake Infinite Campus."""
        schools = []
        for school_id in school_ids:
            self.bucket.write(roster_path(school_id), "roster rows\n")
            schools.append(
                {
                    "name": SCHOOLS.get(school_id, f"School {school_id}"),
                    "id": school_id,
                    "classification": "N",
                    "email": "nurse@example.test",
                    **({"ic_calendar": IC_CALENDARS[school_id]} if ic else {}),
                }
            )
        config = {
            "api": {
                "auth_base_url": self.aisr.auth_url,
                "aisr_api_base_url": self.aisr.base_url,
                "s3_upload_host": "mock-s3-host",
            },
            "district": {"iddis": "0197"},
            "schools": schools,
        }
        if ic:
            config["infinite_campus"] = {
                "base_url": self.aisr.ic_url,
                "app_name": "wstpaul",
                "roster_filter": "MIIC Oct 2023",
            }
        self.bucket.write("config/config.json", json.dumps(config))

    def run(self, cycle: str, capsys) -> tuple[int, dict]:
        """Run one cycle through the job entrypoint; returns (exit code,
        printed result)."""
        before = self.run_ids()
        code = job.main([cycle, "--trigger", "manual"], build=self.build)
        (self.last_run_id,) = self.run_ids() - before
        printed = capsys.readouterr().out.strip().splitlines()[-1]
        self.printed.append(printed)
        return code, json.loads(printed)

    def tick(self, capsys) -> int:
        """Run one tick; an idle tick starts no run, so this returns only
        the exit code (the printed result is in `printed`)."""
        code = job.main(["tick", "--trigger", "scheduled"], build=self.build)
        self.printed.append(capsys.readouterr().out.strip().splitlines()[-1])
        return code

    def build(self, settings: Settings) -> Services:
        """Test composition: the real GCS adapters over the shared fake
        bucket, the fake Drive, and the real config binding and AISR
        adapter."""
        assert settings.data_bucket == self.bucket.name
        clock = Clock(now=lambda: datetime.now(UTC))
        objects = GcsObjectStore(self.bucket)
        return Services(
            settings=settings,
            clock=clock,
            new_ledger=lambda run_id: GcsRunLedger(self.bucket, run_id, now=clock.now),
            objects=objects,
            delivery=self.drive if settings.drive_folder_id else None,
            load_district=lambda: district_from_config(
                json.loads(objects.read_text(CONFIG_PATH)), SECRETS.__getitem__
            ),
        )

    def run_ids(self) -> set[str]:
        """Ids of every run with events (ledger/YYYY/MM/<run_id>/...)."""
        return {
            name.split("/")[3]
            for name in self.bucket.objects
            if name.startswith("ledger/") and not name.startswith("ledger/claims/")
        }

    def latest_run_events(self) -> list[dict]:
        """Events of the run the last `run()` started, in order."""
        runs = read_recent_runs(
            self.bucket, recent_months(datetime.now(), 2), limit=None
        )
        return next(r["events"] for r in runs if r["run_id"] == self.last_run_id)

    def latest_event_types(self) -> list[str]:
        return [event["type"] for event in self.latest_run_events()]


@pytest.fixture
def world(monkeypatch, mock_aisr, caplog):
    """A fresh district with two schools, every edge faked. On teardown,
    asserts no canary PHI reached any log record, printed output, or
    ledger object."""
    caplog.set_level(logging.DEBUG)
    bucket = FakeBucket(BUCKET)
    drive = FakeDrive()

    monkeypatch.setenv("DATA_BUCKET", BUCKET)
    monkeypatch.setenv("DISTRICT_TIME_ZONE", "America/Chicago")
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "e2e-folder")
    # A zero deadline: one staging probe per execution, then go ahead with
    # what is staged (the fake AISR stages at once). Tests of waiting set
    # it back.
    monkeypatch.setenv("POLL_DEADLINE_SECONDS", "0")
    for name in ("DIFF_SANITY_FRACTION", "QUERY_PERIOD_FORMAT", "TRIGGER"):
        monkeypatch.delenv(name, raising=False)

    w = World(bucket=bucket, drive=drive, aisr=mock_aisr)
    w.set_schools(["2542", "2543"])
    yield w

    leaks = find_leaks(caplog.text, w.printed, bucket)
    assert not leaks, f"canary PHI leaked: {leaks[:10]}"


def find_leaks(
    log_text: str, printed: list[str], bucket: FakeBucket
) -> list[tuple[str, str]]:
    """(surface, value) for every canary PHI value found in the logs, the
    printed output, or any ledger object."""
    surfaces = {
        "logs": log_text,
        "printed": "\n".join(printed),
        "ledger": "\n".join(
            text for name, text in bucket.objects.items() if name.startswith("ledger/")
        ),
    }
    return sorted(
        (surface, value)
        for surface, text in surfaces.items()
        for value in CANARY_PHI
        if value in text
    )
