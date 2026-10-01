"""End-to-end harness: the real job entrypoint, end to end, against fakes.

Every test here runs `job.main([...])`, which runs the real cycles, the
real decider and executors, the real AISR adapter (against the in-process
fake AISR), and the real GCS ledger, snapshot, and master code over one
shared FakeBucket. Only the edges are swapped: the storage client, Secret
Manager, and the Drive API.

Two guarantees ride along on every test that uses `world`:

- **No PHI leaves the data path.** Every log record (all loggers, DEBUG
  and up), everything printed, and every ledger object is scanned for
  each value in the fake AISR's CANARY_PHI. The master, diff, and Drive
  files legitimately hold records and are not scanned.
- Nothing reaches real GCP: the seams are patched before the test body.

The seams are patched at the modules that use them. When the composition
root lands, this harness switches to building test services instead, and
the scenarios do not change.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

import pytest
from minnesota_immunization_mock.sample_data import CANARY_PHI

import mn_immunization.pipeline.cycles as cycles
import mn_immunization.runtime.job as job
from mn_immunization.ledger.gcs_ledger import read_recent_runs, recent_months
from tests.conftest import MockAisr
from tests.fakes import FakeBucket, FakeDrive, FakeStorageClient

BUCKET = "e2e-bucket"
SCHOOLS = {"2542": "Friendly Hills Mid", "2543": "Garlough Elementary"}
SECRETS = {
    "aisr-username": "test_user",
    "aisr-password": "test_password",
    "drive-refresh-token": "fake-refresh",
    "drive-client-id": "fake-client",
    "drive-client-secret": "fake-secret",
}


@dataclass
class World:
    bucket: FakeBucket
    drive: FakeDrive
    aisr: MockAisr
    printed: list[str] = field(default_factory=list)
    last_run_id: str = ""

    def set_schools(self, school_ids: list[str]) -> None:
        """Write config.json and a roster per school into the bucket."""
        schools = []
        for school_id in school_ids:
            roster = f"data/queries/{school_id}.csv"
            self.bucket.write(roster, "roster rows\n")
            schools.append(
                {
                    "name": SCHOOLS.get(school_id, f"School {school_id}"),
                    "id": school_id,
                    "classification": "N",
                    "email": "nurse@example.test",
                    "bulk_query_file": roster,
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
        self.bucket.write("config/config.json", json.dumps(config))

    def run(self, cycle: str, capsys) -> tuple[int, dict]:
        """Run one cycle through the job entrypoint; returns (exit code,
        printed result)."""
        before = self.run_ids()
        code = job.main([cycle, "--trigger", "manual"])
        (self.last_run_id,) = self.run_ids() - before
        printed = capsys.readouterr().out.strip().splitlines()[-1]
        self.printed.append(printed)
        return code, json.loads(printed)

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
    client = FakeStorageClient(bucket)

    monkeypatch.setattr(cycles, "get_storage_client", lambda: client)
    monkeypatch.setattr(cycles, "get_secret", SECRETS.__getitem__)
    monkeypatch.setattr(cycles, "GoogleDriveSink", lambda folder_id, secret: drive)

    monkeypatch.setenv("DATA_BUCKET", BUCKET)
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "e2e-folder")
    # One staging probe, then proceed: the fake AISR stages at once.
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "0")
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
