"""Tests for the staged-results polling loop and rerun-safety claims."""

from mn_immunization.ledger.memory import InMemoryRunLedger
from mn_immunization.runtime.cycles import claim_or_proceed, poll_until


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_returns_immediately_when_already_staged():
    fake = FakeClock()
    result = poll_until(
        lambda: 8, target=8, interval_s=14400, deadline_s=72000,
        sleep=fake.sleep, clock=fake.clock,
    )
    assert result == 8
    assert fake.sleeps == []


def test_polls_at_interval_until_target():
    fake = FakeClock()
    results = iter([2, 5, 8])
    result = poll_until(
        lambda: next(results), target=8, interval_s=14400, deadline_s=72000,
        sleep=fake.sleep, clock=fake.clock,
    )
    assert result == 8
    assert fake.sleeps == [14400, 14400]


def test_deadline_caps_total_wait_and_returns_partial():
    fake = FakeClock()
    result = poll_until(
        lambda: 4, target=8, interval_s=14400, deadline_s=30000,
        sleep=fake.sleep, clock=fake.clock,
    )
    assert result == 4
    # Two full intervals, then the remainder up to the deadline; never past it.
    assert sum(fake.sleeps) == 30000
    assert fake.sleeps[-1] < 14400


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
