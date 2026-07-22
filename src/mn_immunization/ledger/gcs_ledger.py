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


class GcsRunLedger:
    """Append-only event writer for a single run.

    The bucket argument is a google.cloud.storage Bucket (or anything with
    a compatible .blob(name).upload_from_string interface).
    """

    def __init__(
        self,
        bucket,
        run_id: str,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.bucket = bucket
        self.run_id = run_id
        self._now = now
        self._seq = 0

    def append(self, event: LedgerEvent) -> None:
        self._seq += 1
        at = self._now()
        blob_name = (
            f"ledger/{at:%Y}/{at:%m}/{self.run_id}/"
            f"{self._seq:03d}_{event.type}.json"
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
        blob = self.bucket.blob(f"ledger/claims/{key}")
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


class GcsSnapshotStore:
    def __init__(self, bucket) -> None:
        self.bucket = bucket

    def put(self, content: str) -> tuple[str, str]:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = f"snapshots/{digest}.csv"
        blob = self.bucket.blob(path)
        try:
            blob.upload_from_string(
                content, content_type="text/csv", if_generation_match=0
            )
        except PreconditionFailed:
            pass  # content-addressed: identical content is already there
        return digest, path


def sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
