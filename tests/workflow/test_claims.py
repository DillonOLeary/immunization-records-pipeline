"""claim_or_proceed: exactly one winner, fail-open on outage.

It guards the date's diff delivery, where acting twice is survivable and
never acting is not. Roster submission does NOT use it: per-school query
claims fail closed (see test_submit_queries.py)."""

from mn_immunization.workflow.support import claim_or_proceed
from tests.fakes import InMemoryRunLedger


def test_diff_claim_wins_exactly_once_per_date():
    ledger = InMemoryRunLedger()
    assert claim_or_proceed(ledger, "2026-07-23_diff") is True
    assert claim_or_proceed(ledger, "2026-07-23_diff") is False
    assert claim_or_proceed(ledger, "2026-07-24_diff") is True


def test_claim_check_failure_proceeds():
    class BrokenLedger:
        def claim(self, key):
            raise ConnectionError("storage outage")

    assert claim_or_proceed(BrokenLedger(), "2026-07-23_diff") is True
