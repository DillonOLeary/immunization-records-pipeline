"""Rosters: the student lists sent to MIIC, in its bulk-query layout.

A roster is pipe-delimited with a header row naming exactly
ROSTER_COLUMNS. Infinite Campus produces it (the district's saved
"MIIC" ad hoc filter); `check_roster` decides whether a fresh export is
fit to send, before it replaces the one on file. Pure: no I/O.
"""

from __future__ import annotations

import csv
import io

ROSTER_COLUMNS = (
    "id_1",
    "id_2",
    "id_3",
    "id_4",
    "id_5",
    "id_6",
    "first_name",
    "last_name",
    "date_of_birth",
    "street_address",
    "other_address",
    "city",
    "state",
    "zip_code",
    "county",
    "sex",
)

MIN_KEPT_FRACTION = 0.5
"""A fresh roster with fewer than half the previous one's students is a
broken filter or a broken export, not enrollment churn."""


class RosterFormatError(ValueError):
    """A roster is not fit to send. Carries what is wrong, never a value."""

    def __init__(self, problem: str):
        super().__init__(problem)
        self.problem = problem


def roster_rows(text: str) -> int:
    """Validate a roster's layout; returns its number of student rows."""
    rows = [row for row in csv.reader(io.StringIO(text), delimiter="|") if row]
    if not rows:
        raise RosterFormatError("empty file")
    if tuple(rows[0]) != ROSTER_COLUMNS:
        raise RosterFormatError("header is not the MIIC bulk-query layout")
    widths = {len(row) for row in rows[1:]}
    if widths - {len(ROSTER_COLUMNS)}:
        raise RosterFormatError("rows do not all have the header's width")
    if len(rows) == 1:
        raise RosterFormatError("no students")
    return len(rows) - 1


def check_roster(text: str, previous: str | None) -> int:
    """Whether a fresh roster may replace `previous` (None: there is none):
    the right layout, and not a collapse in size. Returns its row count."""
    count = roster_rows(text)
    if previous is not None:
        try:
            before = roster_rows(previous)
        except RosterFormatError:
            return count  # the old one was unusable; any valid roster beats it
        if count < before * MIN_KEPT_FRACTION:
            raise RosterFormatError(
                f"{count} students where there were {before}: fewer than half"
            )
    return count
