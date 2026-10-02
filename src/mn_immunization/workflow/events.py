"""Run ledger event types.

An event is a type name plus a small dict of primitive data. Events carry
counts, hashes, ids, and reasons; they never carry record content or any
PHI. The ledger adapter stamps run id, sequence number, and timestamp at
write time.
"""

from __future__ import annotations

from dataclasses import dataclass

# Event types, as stored; writers below and `history.py` share them.
RUN_STARTED = "RunStarted"
PERIOD_OPENED = "PeriodOpened"
PERIOD_CLOSED = "PeriodClosed"
QUERY_SUBMITTED = "QuerySubmitted"
RECORDS_FETCHED = "RecordsFetched"
DIFF_COMPUTED = "DiffComputed"
DELIVERED = "Delivered"
MASTER_COMMITTED = "MasterCommitted"
IMPORT_CONFIRMED = "ImportConfirmed"
RUN_SKIPPED = "RunSkipped"
RUN_WAITING = "RunWaiting"
RUN_COMPLETED = "RunCompleted"
RUN_FAILED = "RunFailed"


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    type: str
    data: dict


def run_started(kind: str, trigger: str) -> LedgerEvent:
    """kind: run|tick|canary|rebaseline; trigger: scheduled|manual."""
    return LedgerEvent(RUN_STARTED, {"kind": kind, "trigger": trigger})


def period_opened(period: str) -> LedgerEvent:
    """`run` opened (or reopened) a period: ticks advance it until it
    closes. Its time starts the staging deadline."""
    return LedgerEvent(PERIOD_OPENED, {"period": period})


def period_closed(period: str, outcome: str) -> LedgerEvent:
    """outcome: success|skipped|blocked|failed, or superseded when a newer
    period opened first. A closed period gets no more ticks; `run` reopens
    it."""
    return LedgerEvent(PERIOD_CLOSED, {"period": period, "outcome": outcome})


def query_submitted(school_id: str, query_file_hash: str, period: str) -> LedgerEvent:
    """One school's roster went to MIIC for `period`. Ledger folders are
    by UTC month, so the period is recorded explicitly; a rerun matches
    on it to know which schools must never be submitted again."""
    return LedgerEvent(
        "QuerySubmitted",
        {"school_id": school_id, "query_file_hash": query_file_hash, "period": period},
    )


def records_fetched(school_id: str, content_hash: str, byte_size: int) -> LedgerEvent:
    return LedgerEvent(
        "RecordsFetched",
        {
            "school_id": school_id,
            "content_hash": content_hash,
            "byte_size": byte_size,
        },
    )


def diff_computed(
    new_count: int,
    total_count: int,
    known_hash: str,
    diff_hash: str,
) -> LedgerEvent:
    return LedgerEvent(
        "DiffComputed",
        {
            "new_count": new_count,
            "total_count": total_count,
            "known_hash": known_hash,
            "diff_hash": diff_hash,
        },
    )


def delivered(
    file_name: str, target: str, remote_id: str | None = None, content_hash: str = ""
) -> LedgerEvent:
    """content_hash is the delivered file's sha256: what makes "this diff
    was already delivered" a statement about content, not about a name."""
    return LedgerEvent(
        "Delivered",
        {
            "file_name": file_name,
            "target": target,
            "remote_id": remote_id or "",
            "content_hash": content_hash,
        },
    )


def master_committed(
    master_hash: str, record_count: int, snapshot_path: str
) -> LedgerEvent:
    """The one event that advances durable state; recorded only after the
    diff was delivered."""
    return LedgerEvent(
        "MasterCommitted",
        {
            "master_hash": master_hash,
            "record_count": record_count,
            "snapshot_path": snapshot_path,
        },
    )


def import_confirmed(file_name: str, how: str) -> LedgerEvent:
    return LedgerEvent(IMPORT_CONFIRMED, {"file_name": file_name, "how": how})


def run_skipped(reason: str) -> LedgerEvent:
    return LedgerEvent(RUN_SKIPPED, {"reason": reason})


def run_waiting(reason: str) -> LedgerEvent:
    """This execution is done but its period is not: results are still
    staging, and the next tick looks again."""
    return LedgerEvent(RUN_WAITING, {"reason": reason})


def run_completed(**summary: int | str) -> LedgerEvent:
    return LedgerEvent(RUN_COMPLETED, dict(summary))


def run_failed(step: str, error: str, **detail: object) -> LedgerEvent:
    """error is an error class or short category, never message content.
    detail carries ids and counts only (e.g. stuck_schools)."""
    return LedgerEvent(RUN_FAILED, {"step": step, "error": error, **detail})


TERMINAL_TYPES = frozenset({RUN_COMPLETED, RUN_SKIPPED, RUN_FAILED, RUN_WAITING})
