"""load_known_records fails closed.

An empty known set disables the sanity brake and makes every current
record "new", so only a master that never existed may load as empty.
These run the real GcsObjectStore over a FakeBucket; the snapshot store
answers whether a master was ever committed.
"""

import pytest
from google.api_core.exceptions import ServiceUnavailable

from mn_immunization.adapters.gcs.storage import GcsObjectStore
from mn_immunization.records.ic_format import IcFormatError
from mn_immunization.records.model import RecordSet
from mn_immunization.workflow.known import (
    MASTER_PATH,
    MasterMissingError,
    load_known_records,
)
from tests.fakes import FakeBucket, InMemorySnapshotStore


def stores(master: str | None, snapshots_exist: bool):
    bucket = FakeBucket()
    if master is not None:
        bucket.write(MASTER_PATH, master)
    snapshots = InMemorySnapshotStore()
    if snapshots_exist:
        snapshots.put("an earlier master\n")
    return GcsObjectStore(bucket), snapshots


def test_master_absent_on_a_first_run_is_an_empty_known_set():
    assert load_known_records(*stores(None, snapshots_exist=False)) == RecordSet()


def test_master_absent_after_a_commit_is_master_missing():
    # Snapshots prove a master was committed; its absence is damage, not a
    # first run. Treating it as empty would deliver the whole known set.
    with pytest.raises(MasterMissingError):
        load_known_records(*stores(None, snapshots_exist=True))


def test_master_empty_after_a_commit_is_master_missing():
    with pytest.raises(MasterMissingError):
        load_known_records(*stores("", snapshots_exist=True))


def test_transient_read_error_propagates():
    class FlakyStore:
        def read_text(self, path):
            raise ServiceUnavailable("try later")

    with pytest.raises(ServiceUnavailable):
        load_known_records(FlakyStore(), InMemorySnapshotStore())


def test_one_malformed_row_fails_the_load():
    # One bad line must not turn the whole known set into zero records.
    master = "12345,678901,MMR,01/15/2024\n12346,678902\n"
    with pytest.raises(IcFormatError):
        load_known_records(*stores(master, snapshots_exist=True))


def test_healthy_master_loads():
    master = "12345,678901,MMR,01/15/2024\n12346,678902,Polio,02/01/2024\n"
    known = load_known_records(*stores(master, snapshots_exist=True))
    assert len(known) == 2
