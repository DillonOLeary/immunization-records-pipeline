"""Domain tests: record validation, deduplication, and diff semantics."""

from datetime import date

import pytest

from mn_immunization.domain.records import (
    RecordSet,
    RecordValidationError,
    VaccinationRecord,
    parse_flexible_date,
)


def record(id_1="12345", id_2="678901", group="MMR", day="01/15/2024"):
    return VaccinationRecord.create(id_1, id_2, group, day)


class TestDateParsing:
    def test_parses_iso_dates_from_aisr(self):
        assert parse_flexible_date("2024-11-17") == date(2024, 11, 17)

    def test_parses_ic_format_dates(self):
        assert parse_flexible_date("11/17/2024") == date(2024, 11, 17)

    def test_rejects_garbage(self):
        with pytest.raises(RecordValidationError):
            parse_flexible_date("not-a-date")

    def test_same_day_in_both_formats_is_equal(self):
        assert parse_flexible_date("2024-11-17") == parse_flexible_date("11/17/2024")


class TestVaccinationRecord:
    def test_empty_id_rejected(self):
        with pytest.raises(RecordValidationError):
            record(id_1="")

    def test_whitespace_id_rejected(self):
        with pytest.raises(RecordValidationError):
            record(id_2="   ")

    def test_empty_vaccine_group_rejected(self):
        with pytest.raises(RecordValidationError):
            record(group="")

    def test_equality_is_full_record(self):
        assert record() == record()
        assert record() != record(day="01/16/2024")
        assert record() != record(group="Polio")


class TestRecordSet:
    def test_from_iterable_dedupes_keeping_first_occurrence_order(self):
        first, second = record(), record(id_1="99")
        record_set = RecordSet.from_iterable([first, second, first])
        assert list(record_set) == [first, second]

    def test_union_dedupes_across_sets(self):
        left = RecordSet.from_iterable([record(), record(id_1="99")])
        right = RecordSet.from_iterable([record(), record(id_1="77")])
        assert len(left.union(right)) == 3

    def test_diff_returns_only_new_records(self):
        known = RecordSet.from_iterable([record()])
        current = RecordSet.from_iterable(
            [record(), record(id_1="99"), record(id_1="77")]
        )
        new = current.diff(known)
        assert len(new) == 2
        assert record() not in new

    def test_diff_of_identical_sets_is_empty(self):
        records = RecordSet.from_iterable([record(), record(id_1="99")])
        assert len(records.diff(records)) == 0

    def test_diff_against_empty_known_returns_everything(self):
        current = RecordSet.from_iterable([record(), record(id_1="99")])
        assert current.diff(RecordSet()) == current

    def test_diff_of_empty_current_is_empty(self):
        known = RecordSet.from_iterable([record()])
        assert len(RecordSet().diff(known)) == 0

    def test_same_person_different_date_or_vaccine_is_new(self):
        # The identity of a record is the full tuple: a second dose (new
        # date) and a different vaccine on the same day are both new facts.
        known = RecordSet.from_iterable([record()])
        current = RecordSet.from_iterable(
            [record(), record(day="01/16/2024"), record(group="Polio")]
        )
        new = current.diff(known)
        assert len(new) == 2

    def test_failed_school_does_not_drift_the_master(self):
        # The real incident: school B's download fails one run, succeeds the
        # next. With master = union(known, current), B's records never leave
        # the master, so B's recovery delivers nothing spurious.
        a, b = record(id_1="school-a"), record(id_1="school-b")
        known = RecordSet.from_iterable([a, b])

        current_without_b = RecordSet.from_iterable([a])
        master_after_bad_run = known.union(current_without_b)
        assert b in master_after_bad_run

        current_with_b_back = RecordSet.from_iterable([a, b])
        assert len(current_with_b_back.diff(master_after_bad_run)) == 0

    def test_date_format_does_not_affect_identity(self):
        # A record parsed from AISR (ISO) must equal the same record parsed
        # back from a master file (IC format), or every diff would re-deliver
        # the entire history.
        from_aisr = record(day="2024-01-15")
        from_master = record(day="01/15/2024")
        assert (
            RecordSet.from_iterable([from_aisr]).diff(
                RecordSet.from_iterable([from_master])
            )
            == RecordSet()
        )
