"""GCS-backed run ledger and snapshot store.

One immutable JSON object per event under ledger/YYYY/MM/<run_id>/; claims
are create-if-absent objects (if_generation_match=0), which makes exactly
one claimant win regardless of concurrent runs; snapshots are
content-addressed CSV objects. No database, no extra IAM surface: the same
bucket the pipeline already uses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from google.api_core.exceptions import PreconditionFailed

from mn_immunization.ledger.events import LedgerEvent

CLAIMS_PREFIX = "ledger/claims/"


class GcsRunLedger:
    """Append-only event writer for a single run, plus the read side every
    run needs: recent runs' events, and the claims held under a prefix.

    The bucket argument is a google.cloud.storage Bucket (or anything with
    a compatible .blob(name) / .list_blobs(prefix) interface).
    """

    def __init__(self, bucket, run_id: str, now: Callable[[], datetime]) -> None:
        self.bucket = bucket
        self.run_id = run_id
        self._now = now
        self._seq = 0

    def append(self, event: LedgerEvent) -> None:
        self._seq += 1
        at = self._now()
        blob_name = (
            f"ledger/{at:%Y}/{at:%m}/{self.run_id}/{self._seq:03d}_{event.type}.json"
        )
        payload = {
            "run_id": self.run_id,
            "seq": self._seq,
            "type": event.type,
            "at": at.isoformat(timespec="seconds"),
            "data": event.data,
        }
        self.bucket.blob(blob_name).upload_from_string(
            json.dumps(payload, indent=2), content_type="application/json"
        )

    def claim(self, key: str) -> bool:
        blob = self.bucket.blob(f"{CLAIMS_PREFIX}{key}")
        payload = json.dumps(
            {"run_id": self.run_id, "at": self._now().isoformat(timespec="seconds")}
        )
        try:
            blob.upload_from_string(
                payload, content_type="application/json", if_generation_match=0
            )
        except PreconditionFailed:
            return False
        return True

    def recent_runs(self, months: int = 2, limit: int | None = None) -> list[dict]:
        """Runs with events in the last `months` calendar months (this one
        included), newest first, each with its events in order."""
        return read_recent_runs(
            self.bucket, recent_months(self._now(), months), limit=limit
        )

    def held_claims(self, prefix: str) -> dict[str, dict]:
        """Every claim whose key starts with prefix: key -> its payload
        (the claimant's run_id and when it claimed)."""
        return read_claims(self.bucket, prefix)


SNAPSHOT_PREFIX = "snapshots/"
"""Every master commit writes a snapshot here, so anything under this
prefix means a master has been committed before."""


class GcsSnapshotStore:
    def __init__(self, bucket) -> None:
        self.bucket = bucket

    def put(self, content: str) -> tuple[str, str]:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = f"{SNAPSHOT_PREFIX}{digest}.csv"
        blob = self.bucket.blob(path)
        try:
            blob.upload_from_string(
                content, content_type="text/csv", if_generation_match=0
            )
        except PreconditionFailed:
            pass  # content-addressed: identical content is already there
        return digest, path

    def any_stored(self) -> bool:
        blobs = self.bucket.list_blobs(prefix=SNAPSHOT_PREFIX, max_results=1)
        return any(True for _ in blobs)


def recent_months(now: datetime, count: int = 2) -> tuple[tuple[int, int], ...]:
    """(year, month) for this month and the count-1 before it, newest first."""
    months = []
    year, month = now.year, now.month
    for _ in range(count):
        months.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return tuple(months)


def read_claims(bucket, prefix: str) -> dict[str, dict]:
    """Claims whose key starts with prefix: key -> payload ({} if the
    payload is unreadable; the claim is held regardless)."""
    claims: dict[str, dict] = {}
    for blob in bucket.list_blobs(prefix=f"{CLAIMS_PREFIX}{prefix}"):
        key = blob.name[len(CLAIMS_PREFIX) :]
        try:
            claims[key] = json.loads(blob.download_as_text())
        except ValueError:
            claims[key] = {}
    return claims


def read_recent_runs(
    bucket, months: tuple[tuple[int, int], ...], limit: int | None = 10
) -> list[dict]:
    """Read runs from the given (year, month) prefixes, newest first.

    Returns one dict per run: run_id plus its events in sequence order
    (all of them when limit is None). Used by the status command, and by
    runs deciding whether a delivery or a roster submission already
    happened.
    """
    events_by_run: dict[str, list[dict]] = {}
    for year, month in months:
        prefix = f"ledger/{year:04d}/{month:02d}/"
        for blob in bucket.list_blobs(prefix=prefix):
            try:
                payload = json.loads(blob.download_as_text())
            except (ValueError, AttributeError):
                continue
            events_by_run.setdefault(payload["run_id"], []).append(payload)

    runs = []
    for run_id, run_events in events_by_run.items():
        run_events.sort(key=lambda e: e["seq"])
        runs.append({"run_id": run_id, "events": run_events})
    runs.sort(key=lambda r: r["events"][0]["at"], reverse=True)
    return runs if limit is None else runs[:limit]
