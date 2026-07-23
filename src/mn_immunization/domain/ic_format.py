"""Rendering and parsing of the Infinite Campus CSV format.

The IC import format is headerless comma-separated rows:
id_1,id_2,vaccine_group,MM/DD/YYYY. Files the old pipeline wrote sometimes
carry extra columns; parsing keeps the first four and ignores the rest,
matching historical behavior.
"""

from __future__ import annotations

import csv
import io

from mn_immunization.domain.records import (
    RecordSet,
    RecordValidationError,
    VaccinationRecord,
)

IC_DATE_FORMAT = "%m/%d/%Y"


class IcFormatError(ValueError):
    """A file does not conform to the Infinite Campus CSV format."""


def render_csv(record_set: RecordSet) -> str:
    """Render a RecordSet as headerless IC-format CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for record in record_set:
        writer.writerow(
            [
                record.id_1,
                record.id_2,
                record.vaccine_group,
                record.vaccination_date.strftime(IC_DATE_FORMAT),
            ]
        )
    return buffer.getvalue()


def chunk(record_set: RecordSet, max_records: int) -> list[RecordSet]:
    """Split a RecordSet into consecutive pieces of at most max_records.

    Used to keep individual Infinite Campus import files a manageable
    size; which records share a file carries no meaning.
    """
    if max_records < 1:
        raise ValueError("max_records must be at least 1")
    records = record_set.records
    return [
        RecordSet(records=records[i : i + max_records])
        for i in range(0, len(records), max_records)
    ]


def parse_ic_csv(text: str) -> RecordSet:
    """Parse headerless IC-format CSV text into a RecordSet."""
    records = []
    for line_number, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not row or not any(field.strip() for field in row):
            continue
        if len(row) < 4:
            raise IcFormatError(
                f"line {line_number}: expected at least 4 columns, got {len(row)}"
            )
        try:
            records.append(VaccinationRecord.create(row[0], row[1], row[2], row[3]))
        except RecordValidationError as error:
            raise IcFormatError(f"line {line_number}: {error}") from error
    return RecordSet.from_iterable(records)
