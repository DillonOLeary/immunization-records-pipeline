"""Rerun-safety claims: exactly one winner, fail-open on outage."""

from mn_immunization.ledger.memory import InMemoryRunLedger
from mn_immunization.pipeline.support import claim_or_proceed


def test_query_claim_makes_reruns_email_safe():
    # A rerun of the unified cycle in the same period loses the query claim
    # and therefore never resubmits rosters (each submission emails every
    # nurse in the district).
    ledger = InMemoryRunLedger()
    assert claim_or_proceed(ledger, "2026-07_query") is True
    assert claim_or_proceed(ledger, "2026-07_query") is False
    assert claim_or_proceed(ledger, "2026-08_query") is True


def test_claim_check_failure_proceeds():
    class BrokenLedger:
        def claim(self, key):
            raise ConnectionError("storage outage")

    assert claim_or_proceed(BrokenLedger(), "2026-07_query") is True
