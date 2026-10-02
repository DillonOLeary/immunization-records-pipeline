"""Vaccination record types and set operations.

Pure: no I/O, no third-party imports. A record is a value; a
RecordSet is an ordered, deduplicated collection of them. Equality on the
full record (both ids, vaccine group, date) is the identity used for
deduplication and diffing, matching how the pipeline has always keyed
records.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime


class RecordValidationError(ValueError):
    """A row could not be turned into a valid vaccination record.

    Carries the field's name and what is wrong with it, never the field's
    value: a shifted column can put a name or a DOB anywhere, and
    exception text travels into logs and tracebacks.
    """

    def __init__(self, field: str, problem: str):
        super().__init__(f"{field} {problem}")
        self.field = field
        self.problem = problem


def parse_flexible_date(raw: str) -> date:
    """Parse the two date formats the pipeline encounters.

    AISR emits ISO dates (2024-11-17); files the pipeline itself wrote use
    Infinite Campus format (11/17/2024).
    """
    text = raw.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        raise RecordValidationError("vaccination_date", "is unparseable") from None


@dataclass(frozen=True, slots=True)
class VaccinationRecord:
    id_1: str
    id_2: str
    vaccine_group: str
    vaccination_date: date

    def __post_init__(self) -> None:
        for field_name in ("id_1", "id_2", "vaccine_group"):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise RecordValidationError(field_name, "is empty")

    @classmethod
    def create(
        cls, id_1: str, id_2: str, vaccine_group: str, raw_date: str
    ) -> VaccinationRecord:
        return cls(
            id_1=id_1,
            id_2=id_2,
            vaccine_group=vaccine_group,
            vaccination_date=parse_flexible_date(raw_date),
        )


@dataclass(frozen=True, slots=True)
class RecordSet:
    """Ordered, deduplicated collection of vaccination records.

    First occurrence wins on duplicates, preserving input order so rendered
    files stay stable and reviewable.
    """

    records: tuple[VaccinationRecord, ...] = ()

    @classmethod
    def from_iterable(cls, records: Iterable[VaccinationRecord]) -> RecordSet:
        return cls(records=tuple(dict.fromkeys(records)))

    def union(self, other: RecordSet) -> RecordSet:
        return RecordSet.from_iterable(self.records + other.records)

    def diff(self, known: RecordSet) -> RecordSet:
        """Records in this set that are not in the known set."""
        known_records = frozenset(known.records)
        return RecordSet(
            records=tuple(r for r in self.records if r not in known_records)
        )

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self) -> Iterator[VaccinationRecord]:
        return iter(self.records)

    def __contains__(self, record: object) -> bool:
        return record in self.records

    def __bool__(self) -> bool:
        return bool(self.records)


EMPTY_RECORD_SET = RecordSet()
