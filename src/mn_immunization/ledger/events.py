"""Run ledger event types.

An event is a type name plus a small dict of primitive data. Events carry
counts, hashes, ids, and reasons; they never carry record content or any
PHI. The ledger adapter stamps run id, sequence number, and timestamp at
write time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    type: str
    data: dict


def run_started(kind: str, trigger: str) -> LedgerEvent:
    """kind: run|canary|rebaseline; trigger: scheduled|manual."""
    return LedgerEvent("RunStarted", {"kind": kind, "trigger": trigger})


def query_submitted(school_id: str, query_file_hash: str) -> LedgerEvent:
    return LedgerEvent(
        "QuerySubmitted",
        {"school_id": school_id, "query_file_hash": query_file_hash},
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


def delivered(file_name: str, target: str, remote_id: str | None = None) -> LedgerEvent:
    return LedgerEvent(
        "Delivered",
        {"file_name": file_name, "target": target, "remote_id": remote_id or ""},
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
    return LedgerEvent("ImportConfirmed", {"file_name": file_name, "how": how})


def run_skipped(reason: str) -> LedgerEvent:
    return LedgerEvent("RunSkipped", {"reason": reason})


def run_completed(**summary: int | str) -> LedgerEvent:
    return LedgerEvent("RunCompleted", dict(summary))


def run_failed(step: str, error: str) -> LedgerEvent:
    """error is an error class or short category, never message content."""
    return LedgerEvent("RunFailed", {"step": step, "error": error})


TERMINAL_TYPES = frozenset({"RunCompleted", "RunSkipped", "RunFailed"})
