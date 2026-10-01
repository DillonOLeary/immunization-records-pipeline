"""Small shared pieces of the pipeline layer: run ids, best-effort ledger
writes, and fail-open claims."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from mn_immunization.ledger.events import LedgerEvent
from mn_immunization.ledger.port import RunLedger

logger = logging.getLogger(__name__)


def new_run_id(kind: str, now: datetime) -> str:
    return f"{kind}_{now:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def append_event(ledger: RunLedger, event: LedgerEvent) -> None:
    """Best-effort ledger append: a ledger write failure must not sink a
    delivery."""
    try:
        ledger.append(event)
    except Exception as error:
        logger.warning(
            "ledger append failed for %s: %s", event.type, type(error).__name__
        )


def claim_or_proceed(ledger: RunLedger, key: str) -> bool:
    """Claim a key; exactly one run can win it. If the claim check itself
    fails (storage outage), proceed: performing an action twice is the old,
    survivable failure mode; performing it zero times is not."""
    try:
        return ledger.claim(key)
    except Exception as error:
        logger.warning(
            "claim check for %s failed (%s); proceeding without guard",
            key,
            type(error).__name__,
        )
        return True
