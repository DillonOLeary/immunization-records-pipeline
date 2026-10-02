"""The known set: fails closed on load, diffs in memory, commits with a
marker.

An empty known set disables the sanity brake and makes every current
record "new", so only a set that was never committed may load as empty.
The marker (a count and a hash, no PHI) is what remembers a commit. These
run the real GcsObjectStore over a FakeBucket.
"""

import json

import pytest
from google.api_core.exceptions import ServiceUnavailable

from mn_immunization.adapters.gcs.storage import GcsObjectStore
from mn_immunization.records.ic_format import IcFormatError, parse_ic_csv
from mn_immunization.records.model import RecordSet
from mn_immunization.workflow.known import (
    KnownRecordsMissingError,
    commit_known,
    diff_against_known,
    load_known_records,
)
from mn_immunization.workflow.layout import KNOWN_MARKER, KNOWN_RECORDS
from tests.fakes import FakeBucket, InMemoryRunLedger

ROWS = "12345,678901,MMR,01/15/2024\n12346,678902,DTaP,02/20/2023\n"


def store(records: str | None = None, marker: bool = False):
    bucket = FakeBucket()
    if records is not None:
        bucket.write(KNOWN_RECORDS, records)
    if marker:
        bucket.write(KNOWN_MARKER, '{"records": 2}')
    return bucket, GcsObjectStore(bucket)


def test_nothing_ever_committed_is_an_empty_known_set():
    assert load_known_records(store()[1]) == RecordSet()


def test_records_absent_after_a_commit_fail_closed():
    # The marker proves a commit happened; the records' absence is damage,
    # not a first run. Treating it as empty would deliver everything.
    with pytest.raises(KnownRecordsMissingError):
        load_known_records(store(marker=True)[1])


def test_records_empty_after_a_commit_fail_closed():
    with pytest.raises(KnownRecordsMissingError):
        load_known_records(store("", marker=True)[1])


def test_a_transient_read_error_propagates():
    class FlakyStore:
        def read_text(self, path):
            raise ServiceUnavailable("try later")

    with pytest.raises(ServiceUnavailable):
        load_known_records(FlakyStore())


def test_one_malformed_row_fails_the_load():
    # One bad line must not turn the whole known set into zero records.
    with pytest.raises(IcFormatError):
        load_known_records(store(ROWS + "12347,678903\n", marker=True)[1])


def test_the_diff_is_what_is_new_and_the_known_set_grows_by_the_fetch():
    _, objects = store(ROWS, marker=True)
    current = parse_ic_csv("12345,678901,MMR,01/15/2024\n99999,888888,Flu,10/01/2026\n")
    ledger = InMemoryRunLedger()

    new, known_after, known_count = diff_against_known(current, objects, ledger)

    assert [r.id_1 for r in new] == ["99999"]
    assert len(known_after) == 3  # absence from a fetch is never deletion
    assert known_count == 2
    assert ledger.event_types() == ["DiffComputed"]


def test_commit_writes_the_records_then_the_marker():
    bucket, objects = store()
    ledger = InMemoryRunLedger()

    commit_known(objects, parse_ic_csv(ROWS), ledger)

    assert bucket.objects[KNOWN_RECORDS] == ROWS
    marker = json.loads(bucket.objects[KNOWN_MARKER])
    assert marker["records"] == 2
    assert len(marker["sha256"]) == 64
    assert ledger.event_types() == ["MasterCommitted"]
    # and the next load sees it
    assert len(load_known_records(objects)) == 2
