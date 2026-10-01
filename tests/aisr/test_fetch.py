"""AisrClient.fetch_latest_records: download and parse, at the AISR edge.

The source owns its file format. A school's results come back parsed,
with the raw file's hash and size for the ledger; a file the parser
rejects (what a MIIC format change looks like) raises, and the error
names a line and a field, never a value.
"""

import pytest
from minnesota_immunization_mock.sample_data import expected_ic_rows

from mn_immunization.domain.ic_format import render_csv
from mn_immunization.sources.aisr.client import aisr_opener
from mn_immunization.sources.aisr.parsing import AisrParseError
from mn_immunization.sources.aisr.port import AISRActionFailedError

SECRETS = {"aisr-username": "test_user", "aisr-password": "test_password"}


def open_source(mock_aisr):
    return aisr_opener(SECRETS.__getitem__)(mock_aisr.auth_url, mock_aisr.base_url)


def test_fetch_returns_parsed_records_and_the_raw_file_shape(mock_aisr):
    with open_source(mock_aisr) as source:
        fetched = source.fetch_latest_records("2542")

    assert render_csv(fetched.records).splitlines() == expected_ic_rows("2542")
    assert len(fetched.content_hash) == 64
    assert fetched.byte_size > 0


def test_a_changed_format_raises_a_parse_error(mock_aisr):
    mock_aisr.faults.malformed_results.add("2542")

    with open_source(mock_aisr) as source, pytest.raises(AisrParseError):
        source.fetch_latest_records("2542")


def test_no_results_listed_raises(mock_aisr):
    mock_aisr.faults.no_results.add("2543")

    with open_source(mock_aisr) as source, pytest.raises(AISRActionFailedError):
        source.fetch_latest_records("2543")


def test_the_opener_reads_credentials_once_per_run(mock_aisr):
    reads = []

    def secret(name):
        reads.append(name)
        return SECRETS[name]

    opener = aisr_opener(secret)
    for _ in range(3):
        with opener(mock_aisr.auth_url, mock_aisr.base_url):
            pass

    assert reads == ["aisr-username", "aisr-password"]
