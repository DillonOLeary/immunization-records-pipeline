"""Parsing of AISR bulk-query result files.

AISR delivers pipe-delimited CSV with a header row and many columns; the
pipeline needs four of them. Format knowledge lives here at the AISR edge,
not in the domain.
"""

from __future__ import annotations

import csv
import io

from mn_immunization.domain.records import (
    RecordSet,
    RecordValidationError,
    VaccinationRecord,
)

REQUIRED_COLUMNS = ("id_1", "id_2", "vaccine_group_name", "vaccination_date")


class AisrParseError(ValueError):
    """An AISR results file could not be parsed."""


def parse_aisr_csv(text: str) -> RecordSet:
    """Parse pipe-delimited AISR results text into a RecordSet."""
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    header = reader.fieldnames or []
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise AisrParseError(f"missing required column(s): {', '.join(missing)}")

    records = []
    for line_number, row in enumerate(reader, start=2):
        try:
            records.append(
                VaccinationRecord.create(
                    row["id_1"],
                    row["id_2"],
                    row["vaccine_group_name"],
                    row["vaccination_date"],
                )
            )
        except RecordValidationError as error:
            raise AisrParseError(f"line {line_number}: {error}") from error
    return RecordSet.from_iterable(records)
