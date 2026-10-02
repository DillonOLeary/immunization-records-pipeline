"""Deterministic fake AISR results, seeded with canary PHI.

Every name, date of birth, and student id here is invented. They are
distinctive on purpose: tests scan logs, stdout, and ledger objects for
every value in CANARY_PHI, and any match means record content leaked.
Student ids start with 81/91 and dates fall in 2008-2021, so none of them
collide with school ids, run ids, or timestamps a log line may carry.

Output is identical on every call (no randomness, no clock), so tests can
assert exact diffs and file hashes.
"""

from __future__ import annotations

from datetime import date

HEADER = "id_1|id_2|name|dob|vaccine_group_name|vaccination_date"

VACCINES = ("MMR", "DTaP", "Polio", "Hepatitis B", "Varicella", "Flu")

# (id_1, id_2, name, dob) per school.
STUDENTS: dict[str, list[tuple[str, str, str, str]]] = {
    "2542": [  # Friendly Hills Mid
        ("8100231", "9100231", "Zelda Canaryfield", "2010-03-14"),
        ("8100232", "9100232", "Quincy Larkspurr", "2011-07-02"),
        ("8100233", "9100233", "Odalys Wrenwhistle", "2009-11-23"),
    ],
    "2543": [  # Garlough Elementary
        ("8100341", "9100341", "Barnaby Thistlequill", "2014-01-30"),
        ("8100342", "9100342", "Mireille Foxglovey", "2013-05-19"),
    ],
}

BRAKE_SCHOOL_ID = "2544"
"""A school large enough to trip the sanity brake: 20 students with 4
vaccinations each is 80 records, more than max(50, 20% of a small known
set)."""

STUDENTS[BRAKE_SCHOOL_ID] = [
    (
        f"81005{n:02d}",
        f"91005{n:02d}",
        f"Pemberton Ashgrove{n:02d}",
        f"2008-02-{n + 1:02d}",
    )
    for n in range(20)
]

DEFAULT_SCHOOL = "default"
STUDENTS[DEFAULT_SCHOOL] = [
    ("8100901", "9100901", "Ignatius Moonfellow", "2012-09-09"),
]


def _vaccination_date(student: int, dose: int) -> date:
    return date(
        2019 + (student + dose) % 3,
        1 + (student * 5 + dose) % 12,
        1 + (student * 7 + dose * 3) % 28,
    )


def _rows(school_id: str) -> list[tuple[str, str, str, str, str, str]]:
    students = STUDENTS.get(school_id, STUDENTS[DEFAULT_SCHOOL])
    doses = 4 if school_id == BRAKE_SCHOOL_ID else 2
    rows = []
    for s, (id_1, id_2, name, dob) in enumerate(students):
        for d in range(doses):
            vaccine = VACCINES[(s + d) % len(VACCINES)]
            rows.append(
                (id_1, id_2, name, dob, vaccine, _vaccination_date(s, d).isoformat())
            )
    return rows


def get_sample_vaccination_data(school_id: str) -> str:
    """AISR results text (pipe-delimited, ISO dates) for a school."""
    lines = [HEADER, *("|".join(row) for row in _rows(school_id))]
    return "\n".join(lines) + "\n"


def expected_ic_rows(school_id: str) -> list[str]:
    """The same records as the pipeline renders them for Infinite Campus:
    headerless id_1,id_2,vaccine,MM/DD/YYYY."""
    out = []
    for id_1, id_2, _name, _dob, vaccine, iso in _rows(school_id):
        y, m, d = iso.split("-")
        out.append(f"{id_1},{id_2},{vaccine},{m}/{d}/{y}")
    return out


ROSTER_HEADER = (
    "id_1|id_2|id_3|id_4|id_5|id_6|first_name|last_name|date_of_birth|"
    "street_address|other_address|city|state|zip_code|county|sex"
)


def _street(n: int) -> str:
    return f"{n + 1} Wrenwhistle Way"


def roster_csv(school_id: str) -> str:
    """A school's roster as Infinite Campus exports it through the MIIC
    filter: MIIC's bulk-query layout, pipe-delimited, with a header."""
    students = STUDENTS.get(school_id, STUDENTS[DEFAULT_SCHOOL])
    rows = [
        "|".join(
            [id_1, id_2, f"7{id_1}", "", "", "", *name.split(" ", 1), dob]
            + [_street(n), "", "Mendota Heights", "MN", "55118", "Dakota", "F"]
        )
        for n, (id_1, id_2, name, dob) in enumerate(students)
    ]
    return "\n".join([ROSTER_HEADER, *rows]) + "\n"


def _canary_values() -> frozenset[str]:
    values: set[str] = set()
    for students in STUDENTS.values():
        for n, (id_1, id_2, name, dob) in enumerate(students):
            values.update({id_1, id_2, dob, *name.split(), _street(n)})
    for school_id in STUDENTS:
        for row in _rows(school_id):
            iso = row[5]
            y, m, d = iso.split("-")
            values.update({iso, f"{m}/{d}/{y}"})
    return frozenset(values)


CANARY_PHI: frozenset[str] = _canary_values()
"""Every student-identifying value the mock can emit: ids, name parts,
DOBs, and vaccination dates in both formats. None may appear in logs,
stdout, or ledger events."""
