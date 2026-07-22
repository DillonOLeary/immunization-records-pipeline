"""GCS ledger adapter tests against a fake bucket honoring generation
preconditions — the mechanism the claim guarantee rests on."""

import json
from datetime import datetime

import pytest
from google.api_core.exceptions import PreconditionFailed

from mn_immunization.ledger import events
from mn_immunization.ledger.gcs_ledger import GcsRunLedger, GcsSnapshotStore


class FakeBlob:
    def __init__(self, store: dict, name: str):
        self.store = store
        self.name = name

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        if if_generation_match == 0 and self.name in self.store:
            raise PreconditionFailed(f"object {self.name} already exists")
        self.store[self.name] = data


class FakeBucket:
    def __init__(self):
        self.objects: dict[str, str] = {}

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self.objects, name)


def fixed_now():
    return datetime(2026, 7, 22, 9, 0, 0)


@pytest.fixture
def bucket():
    return FakeBucket()


def test_append_writes_one_object_per_event_with_sequence(bucket):
    ledger = GcsRunLedger(bucket, run_id="download_x", now=fixed_now)
    ledger.append(events.run_started("download", "scheduled"))
    ledger.append(events.run_completed(schools=8))

    names = sorted(bucket.objects)
    assert names == [
        "ledger/2026/07/download_x/001_RunStarted.json",
        "ledger/2026/07/download_x/002_RunCompleted.json",
    ]
    payload = json.loads(bucket.objects[names[0]])
    assert payload["run_id"] == "download_x"
    assert payload["seq"] == 1
    assert payload["at"] == "2026-07-22T09:00:00"
    assert payload["data"] == {"kind": "download", "trigger": "scheduled"}


def test_claim_wins_once_across_separate_runs(bucket):
    first_run = GcsRunLedger(bucket, run_id="run-a", now=fixed_now)
    second_run = GcsRunLedger(bucket, run_id="run-b", now=fixed_now)

    assert first_run.claim("2026-07-22_diff") is True
    assert second_run.claim("2026-07-22_diff") is False
    assert second_run.claim("2026-07-23_diff") is True

    claim = json.loads(bucket.objects["ledger/claims/2026-07-22_diff"])
    assert claim["run_id"] == "run-a"


def test_snapshots_are_content_addressed_and_idempotent(bucket):
    store = GcsSnapshotStore(bucket)
    digest_a, path_a = store.put("1,2,MMR,01/15/2024\n")
    digest_b, path_b = store.put("1,2,MMR,01/15/2024\n")

    assert (digest_a, path_a) == (digest_b, path_b)
    assert path_a == f"snapshots/{digest_a}.csv"
    assert bucket.objects[path_a] == "1,2,MMR,01/15/2024\n"
