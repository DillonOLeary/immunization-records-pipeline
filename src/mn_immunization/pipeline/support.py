"""Small shared pieces of the pipeline layer: run ids, best-effort ledger
writes, fail-open claims, polling, and the diff sanity policy."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime

logger = logging.getLogger(__name__)


def new_run_id(kind: str) -> str:
    return f"{kind}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def append_event(ledger, event) -> None:
    """Best-effort ledger append: a ledger write failure must not sink a
    delivery."""
    try:
        ledger.append(event)
    except Exception as error:
        logger.warning("ledger append failed for %s: %s", event.type, error)


def claim_or_proceed(ledger, key: str) -> bool:
    """Claim a key; exactly one run can win it. If the claim check itself
    fails (storage outage), proceed: performing an action twice is the old,
    survivable failure mode; performing it zero times is not."""
    try:
        return ledger.claim(key)
    except Exception as error:
        logger.warning(
            "claim check for %s failed (%s); proceeding without guard", key, error
        )
        return True


def suspicious_diff(new_count: int, known_count: int, fraction: float = 0.2) -> bool:
    """A diff far larger than history is a symptom, not a delivery.

    A wiped or mismatched master would diff the entire student body as
    "new" and flood the nurses with duplicates. When the known set is
    non-empty and the diff exceeds max(50, fraction*known), block Drive
    delivery and fail the run loudly instead. A genuine first run (empty
    known set) is never blocked.
    """
    if known_count == 0:
        return False
    return new_count > max(50, int(fraction * known_count))


def poll_until(
    check: Callable[[], int],
    target: int,
    interval_s: float,
    deadline_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Run check() until it reaches target or the deadline passes.

    Checks immediately, then every interval_s. Returns the last check
    result, which callers compare against target to distinguish success
    from timeout.
    """
    start = clock()
    while True:
        current = check()
        if current >= target:
            return current
        remaining = deadline_s - (clock() - start)
        if remaining <= 0:
            return current
        sleep(min(interval_s, remaining))
