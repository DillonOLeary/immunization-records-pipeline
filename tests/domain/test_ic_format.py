"""Tests for Infinite Campus CSV rendering and parsing."""

import pytest

from mn_immunization.domain.ic_format import (
    IcFormatError,
    parse_ic_csv,
    render_csv,
)
from mn_immunization.domain.records import RecordSet, VaccinationRecord


def record(id_1="123", id_2="456", group="COVID-19", day="11/17/2024"):
    return VaccinationRecord.create(id_1, id_2, group, day)


class TestRender:
    def test_renders_headerless_comma_rows_with_ic_dates(self):
        records = RecordSet.from_iterable(
            [
                record(),
                record(id_1="789", id_2="101", group="Flu", day="11/16/2024"),
            ]
        )
        assert render_csv(records) == (
            "123,456,COVID-19,11/17/2024\n789,101,Flu,11/16/2024\n"
        )

    def test_iso_input_renders_as_ic_date(self):
        records = RecordSet.from_iterable([record(day="2024-11-17")])
        assert render_csv(records) == "123,456,COVID-19,11/17/2024\n"

    def test_empty_set_renders_empty_text(self):
        assert render_csv(RecordSet()) == ""


class TestChunk:
    def make_set(self, count):
        from mn_immunization.domain.ic_format import chunk  # noqa: F401

        return RecordSet.from_iterable(record(id_1=str(1000 + i)) for i in range(count))

    def test_splits_into_bounded_pieces_preserving_order(self):
        from mn_immunization.domain.ic_format import chunk

        pieces = chunk(self.make_set(25), max_records=10)
        assert [len(p) for p in pieces] == [10, 10, 5]
        reassembled = [r for p in pieces for r in p]
        assert reassembled == list(self.make_set(25))

    def test_empty_set_yields_no_files(self):
        from mn_immunization.domain.ic_format import chunk

        assert chunk(RecordSet(), max_records=10) == []

    def test_rejects_nonpositive_chunk_size(self):
        from mn_immunization.domain.ic_format import chunk

        with pytest.raises(ValueError):
            chunk(self.make_set(3), max_records=0)


class TestParse:
    def test_roundtrips_with_render(self):
        records = RecordSet.from_iterable([record(), record(id_1="789", group="Flu")])
        assert parse_ic_csv(render_csv(records)) == records

    def test_extra_columns_are_ignored(self):
        text = "123,456,MMR,01/15/2024,extra,columns\n"
        parsed = parse_ic_csv(text)
        assert len(parsed) == 1
        assert parsed.records[0].vaccine_group == "MMR"

    def test_blank_lines_are_skipped(self):
        parsed = parse_ic_csv("123,456,MMR,01/15/2024\n\n")
        assert len(parsed) == 1

    def test_too_few_columns_raises_with_line_number(self):
        with pytest.raises(IcFormatError, match="line 2"):
            parse_ic_csv("123,456,MMR,01/15/2024\n123,456\n")

    def test_bad_date_raises_with_line_number(self):
        with pytest.raises(IcFormatError, match="line 1"):
            parse_ic_csv("123,456,MMR,someday\n")

    def test_parsing_dedupes(self):
        text = "123,456,MMR,01/15/2024\n123,456,MMR,01/15/2024\n"
        assert len(parse_ic_csv(text)) == 1
