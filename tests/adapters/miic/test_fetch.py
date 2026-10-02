"""AisrClient.fetch_latest_records: download and parse, at the AISR edge.

The source owns its file format. A school's results come back parsed,
with the raw file's hash and size for the ledger; a file the parser
rejects (what a MIIC format change looks like) raises, and the error
names a line and a field, never a value.
"""

import pytest
from minnesota_immunization_mock.sample_data import expected_ic_rows

from mn_immunization.adapters.miic.actions import AISRActionFailedError, DistrictInfo
from mn_immunization.adapters.miic.client import SchoolUpload, aisr_opener
from mn_immunization.adapters.miic.parsing import AisrParseError
from mn_immunization.records.ic_format import render_csv
from mn_immunization.workflow.ports import RosterNotSentError, School

SECRETS = {"aisr-username": "test_user", "aisr-password": "test_password"}


DISTRICT = DistrictInfo(iddis="0197", s3_upload_host="mock-s3-host")


def open_registry(mock_aisr, uploads=None):
    return aisr_opener(
        SECRETS.__getitem__,
        mock_aisr.auth_url,
        mock_aisr.base_url,
        DISTRICT,
        uploads=uploads or {},
    )()


def test_fetch_returns_parsed_records_and_the_raw_file_shape(mock_aisr):
    with open_registry(mock_aisr) as source:
        fetched = source.fetch_latest_records("2542")

    assert render_csv(fetched.records).splitlines() == expected_ic_rows("2542")
    assert len(fetched.content_hash) == 64
    assert fetched.byte_size > 0


def test_a_changed_format_raises_a_parse_error(mock_aisr):
    mock_aisr.faults.malformed_results.add("2542")

    with open_registry(mock_aisr) as source, pytest.raises(AisrParseError):
        source.fetch_latest_records("2542")


def test_no_results_listed_raises(mock_aisr):
    mock_aisr.faults.no_results.add("2543")

    with open_registry(mock_aisr) as source, pytest.raises(AISRActionFailedError):
        source.fetch_latest_records("2543")


def test_the_opener_reads_credentials_once_per_run(mock_aisr):
    reads = []

    def secret(name):
        reads.append(name)
        return SECRETS[name]

    opener = aisr_opener(
        secret, mock_aisr.auth_url, mock_aisr.base_url, DISTRICT, uploads={}
    )
    for _ in range(3):
        with opener():
            pass

    assert reads == ["aisr-username", "aisr-password"]


def test_a_roster_goes_up_with_the_schools_upload_metadata(mock_aisr):
    uploads = {"2542": SchoolUpload("N", "nurse@example.test")}
    with open_registry(mock_aisr, uploads) as registry:
        registry.submit_roster(School("2542", "Friendly Hills"), "rows\n")

    assert mock_aisr.received_uploads == ["2542"]


def test_a_school_without_upload_metadata_is_never_sent(mock_aisr):
    # A config mismatch is caught before anything reaches MDH, as the one
    # failure after which a retry is safe.
    with open_registry(mock_aisr) as registry, pytest.raises(RosterNotSentError):
        registry.submit_roster(School("2542", "Friendly Hills"), "rows\n")

    assert mock_aisr.received_uploads == []
