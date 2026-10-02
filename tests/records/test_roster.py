"""A fresh roster replaces the one on file only if it is fit to send."""

import pytest

from mn_immunization.records.roster import (
    ROSTER_COLUMNS,
    RosterFormatError,
    check_roster,
    roster_rows,
)

HEADER = "|".join(ROSTER_COLUMNS)


def roster(students: int, header: str = HEADER) -> str:
    row = "|".join(["81"] + [""] * (len(ROSTER_COLUMNS) - 1))
    return "\n".join([header, *[row] * students]) + "\n"


def test_a_well_formed_roster_counts_its_students():
    assert roster_rows(roster(3)) == 3


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("", "empty file"),
        (roster(3, header="id_1|name|dob"), "header is not the MIIC bulk-query layout"),
        (HEADER + "\n81|91\n", "rows do not all have the header's width"),
        (HEADER + "\n", "no students"),
    ],
)
def test_malformed_rosters_are_refused_naming_the_problem(text, problem):
    with pytest.raises(RosterFormatError) as caught:
        roster_rows(text)
    assert caught.value.problem == problem


def test_a_roster_that_lost_more_than_half_its_students_is_refused():
    with pytest.raises(RosterFormatError):
        check_roster(roster(4), previous=roster(10))


def test_ordinary_churn_and_first_rosters_pass():
    assert check_roster(roster(906), previous=roster(915)) == 906
    assert check_roster(roster(5), previous=None) == 5
    assert check_roster(roster(5), previous="garbage") == 5


def test_the_problem_never_carries_a_value():
    # Messages reach logs; a roster row is PHI.
    with pytest.raises(RosterFormatError) as caught:
        roster_rows(HEADER + "\nZelda|Canaryfield\n")
    assert "Zelda" not in str(caught.value)
