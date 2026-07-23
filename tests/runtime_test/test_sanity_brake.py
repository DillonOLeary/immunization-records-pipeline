"""Tests for the diff-size sanity brake."""

from mn_immunization.runtime.cycles import suspicious_diff


def test_first_ever_run_is_never_blocked():
    assert suspicious_diff(new_count=4200, known_count=0) is False


def test_normal_monthly_diff_passes():
    assert suspicious_diff(new_count=40, known_count=4000) is False


def test_wiped_master_flood_is_blocked():
    # Master lost or id-mismatched: nearly everything diffs as "new".
    assert suspicious_diff(new_count=3900, known_count=4000) is True


def test_small_absolute_diffs_pass_even_against_small_history():
    # The floor of 50 keeps tiny districts from tripping on normal churn.
    assert suspicious_diff(new_count=45, known_count=100) is False
    assert suspicious_diff(new_count=51, known_count=100) is True
