"""Tests for parsing AISR bulk-query result files."""

from pathlib import Path

import pytest

from mn_immunization.domain.records import RecordSet
from mn_immunization.sources.aisr.parsing import AisrParseError, parse_aisr_csv

MOCK_DOWNLOAD = Path(__file__).parent.parent / "test_data" / "mock_aisr_download.csv"


def test_parses_the_real_aisr_fixture():
    records = parse_aisr_csv(MOCK_DOWNLOAD.read_text(encoding="utf-8"))
    assert len(records) > 0
    first = records.records[0]
    assert first.id_1 == "93810"
    assert first.vaccine_group == "Varicella"
    assert first.vaccination_date.isoformat() == "2022-11-18"


def test_parses_pipe_delimited_with_header():
    text = (
        "id_1|id_2|vaccine_group_name|vaccination_date\n"
        "123|456|COVID-19|11/17/2024\n"
        "789|101|Flu|11/16/2024\n"
    )
    records = parse_aisr_csv(text)
    assert len(records) == 2
    assert records.records[0].id_1 == "123"


def test_missing_required_column_raises():
    text = "id_1|id_2|vaccination_date\n123|456|11/17/2024\n"
    with pytest.raises(AisrParseError, match="vaccine_group_name"):
        parse_aisr_csv(text)


def test_bad_row_raises_with_line_number():
    text = (
        "id_1|id_2|vaccine_group_name|vaccination_date\n"
        "123|456|COVID-19|not-a-date\n"
    )
    with pytest.raises(AisrParseError, match="line 2"):
        parse_aisr_csv(text)


def test_extra_columns_in_real_format_are_ignored():
    text = (
        "id_1|id_2|extra|vaccine_group_name|vaccination_date|more\n"
        "123|456|x|COVID-19|2024-11-17|y\n"
    )
    records = parse_aisr_csv(text)
    assert records == RecordSet.from_iterable(
        [records.records[0]]
    )
    assert records.records[0].vaccine_group == "COVID-19"
