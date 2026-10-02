"""Test doubles shared across the suite.

FakeBucket stands in for a google.cloud.storage Bucket at the surface the
pipeline's GCS adapters use. It honors the one semantic the claim
guarantee rests on, `if_generation_match=0` (create only if absent), and
raises the real NotFound / PreconditionFailed exceptions, so adapter code
under test takes its real error paths. `fail_next_write` injects one
failure into a named object's next write, to crash a run at an exact
point. FakeStorageClient wraps it as a client; FakeDrive records what was
delivered to the Drive folder. InMemoryRunLedger and InMemorySnapshotStore
are the ledger ports with nothing behind them, for unit tests that need a
ledger but not storage semantics.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.api_core.exceptions import NotFound, PreconditionFailed

from mn_immunization.gcp.storage import GcsObjectStore
from mn_immunization.ledger.events import LedgerEvent
from mn_immunization.pipeline.context import RunContext
from mn_immunization.pipeline.periods import period_key
from mn_immunization.pipeline.services import Clock
from mn_immunization.pipeline.settings import Settings
from mn_immunization.sources.aisr.port import DistrictInfo, SchoolQueryInformation


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str):
        self.bucket = bucket
        self.name = name

    @property
    def generation(self) -> int | None:
        return self.bucket.generations.get(self.name)

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        self.bucket.maybe_fail(self.name)
        if if_generation_match == 0 and self.name in self.bucket.objects:
            raise PreconditionFailed(f"object {self.name} already exists")
        self.bucket.write(self.name, data if isinstance(data, str) else data.decode())

    def upload_from_filename(self, filename, content_type=None):
        self.bucket.maybe_fail(self.name)
        self.bucket.write(self.name, Path(filename).read_text(encoding="utf-8"))

    def download_as_text(self) -> str:
        if self.name not in self.bucket.objects:
            raise NotFound(f"object {self.name} not found")
        return self.bucket.objects[self.name]

    def download_to_filename(self, filename) -> None:
        Path(filename).write_text(self.download_as_text(), encoding="utf-8")

    def delete(self, if_generation_match=None) -> None:
        if self.name not in self.bucket.objects:
            raise NotFound(f"object {self.name} not found")
        if if_generation_match is not None and if_generation_match != self.generation:
            raise PreconditionFailed(f"object {self.name} generation changed")
        del self.bucket.objects[self.name]
        del self.bucket.generations[self.name]


class FakeBucket:
    """In-memory objects: name -> text, plus a generation per write."""

    def __init__(self, name: str = "test-bucket"):
        self.name = name
        self.objects: dict[str, str] = {}
        self.generations: dict[str, int] = {}
        self._next_generation = 1
        self._failures: dict[str, Exception] = {}

    def fail_next_write(self, name: str, error: Exception) -> None:
        self._failures[name] = error

    def maybe_fail(self, name: str) -> None:
        error = self._failures.pop(name, None)
        if error is not None:
            raise error

    def write(self, name: str, text: str) -> None:
        self.objects[name] = text
        self.generations[name] = self._next_generation
        self._next_generation += 1

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)

    def list_blobs(self, prefix: str = "", max_results: int | None = None):
        names = [name for name in sorted(self.objects) if name.startswith(prefix)]
        if max_results is not None:
            names = names[:max_results]
        return [FakeBlob(self, name) for name in names]


class FakeStorageClient:
    """A storage.Client serving exactly one FakeBucket."""

    def __init__(self, bucket: FakeBucket):
        self._bucket = bucket

    def bucket(self, name: str) -> FakeBucket:
        assert name == self._bucket.name, f"unexpected bucket {name}"
        return self._bucket

    def list_blobs(self, bucket_name: str, prefix: str = "", max_results=None):
        return self.bucket(bucket_name).list_blobs(prefix, max_results)


class FakeDrive:
    """A DriveSink: the import queue, with what was uploaded and what is
    still there (staff delete a file once imported). `list_error` makes
    listing fail."""

    def __init__(self, list_error: Exception | None = None):
        self.files: dict[str, str] = {}
        self.uploads: list[str] = []
        self.list_error = list_error

    def upload(self, path: Path, name: str) -> str:
        self.files[name] = Path(path).read_text(encoding="utf-8")
        self.uploads.append(name)
        return f"drive-file-{len(self.uploads)}"

    def list_filenames(self) -> set[str]:
        if self.list_error is not None:
            raise self.list_error
        return set(self.files)


class InMemoryRunLedger:
    """`history` is earlier runs' event envelopes, as recent_runs would
    read them from storage; `claims` maps each held key to its payload."""

    def __init__(
        self,
        run_id: str = "test-run",
        now: Callable[[], datetime] = datetime.now,
        history: list[dict] | None = None,
    ) -> None:
        self.run_id = run_id
        self._now = now
        self.events: list[dict] = []
        self.history: list[dict] = list(history or [])
        self.claims: dict[str, dict] = {}

    def append(self, event: LedgerEvent) -> None:
        self.events.append(
            {
                "run_id": self.run_id,
                "seq": len(self.events) + 1,
                "type": event.type,
                "at": self._now().isoformat(timespec="seconds"),
                "data": event.data,
            }
        )

    def claim(self, key: str) -> bool:
        if key in self.claims:
            return False
        self.claims[key] = {
            "run_id": self.run_id,
            "at": self._now().isoformat(timespec="seconds"),
        }
        return True

    def release(self, key: str) -> None:
        if self.claims.get(key, {}).get("run_id") != self.run_id:
            raise ValueError(f"claim {key} was not won by run {self.run_id}")
        del self.claims[key]

    def recent_runs(self, months: int = 2, limit: int | None = None) -> list[dict]:
        by_run: dict[str, list[dict]] = {}
        for event in [*self.history, *self.events]:
            by_run.setdefault(event["run_id"], []).append(event)
        runs = [
            {"run_id": run_id, "events": sorted(evs, key=lambda e: e["seq"])}
            for run_id, evs in by_run.items()
        ]
        runs.sort(key=lambda r: r["events"][0]["at"], reverse=True)
        return runs if limit is None else runs[:limit]

    def held_claims(self, prefix: str) -> dict[str, dict]:
        return {k: v for k, v in self.claims.items() if k.startswith(prefix)}

    def event_types(self) -> list[str]:
        return [event["type"] for event in self.events]


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, str] = {}

    def put(self, content: str) -> tuple[str, str]:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = f"snapshots/{digest}.csv"
        self.snapshots[path] = content
        return digest, path

    def any_stored(self) -> bool:
        return bool(self.snapshots)


DISTRICT = ZoneInfo("America/Chicago")
"""The test district's zone (ISD 197's)."""


def district_period(now: datetime | None = None) -> str:
    """This month's roster period in the test district: the default
    QUERY_PERIOD_FORMAT, in the district's zone."""
    return (now or datetime.now(UTC)).astimezone(DISTRICT).strftime("%Y-%m")


class FakeClock:
    """Wall time fixed at `at` (UTC-aware, like the real clock), moved only
    by `advance`."""

    def __init__(self, at: datetime | None = None):
        self.at = at or datetime.now(UTC)

    def now(self) -> datetime:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)

    def as_clock(self) -> Clock:
        return Clock(now=self.now)


def no_source(auth_url: str, api_url: str):
    raise AssertionError("no AISR session expected in this test")


_DEFAULT = object()


def make_run_context(
    tmp_path: Path,
    *,
    settings: Settings | None = None,
    clock: Clock | None = None,
    ledger=None,
    objects=None,
    drive=_DEFAULT,
    open_source=no_source,
    schools: list[SchoolQueryInformation] | None = None,
    roster_paths: dict[str, str] | None = None,
    opened_at: datetime | None = None,
) -> RunContext:
    """A RunContext of fakes: in-memory ledger and snapshots, a FakeBucket
    object store, a FakeDrive, and an AISR opener that must not be used.
    Its period is the one current at the clock's time, opened then unless
    `opened_at` says otherwise. Pass `drive=None` for a district with no
    delivery folder."""
    settings = settings or Settings(data_bucket="test-bucket", time_zone=DISTRICT)
    clock = clock or FakeClock().as_clock()
    now = clock.now()
    return RunContext(
        settings=settings,
        clock=clock,
        ledger=ledger or InMemoryRunLedger(),
        snapshots=InMemorySnapshotStore(),
        objects=objects or GcsObjectStore(FakeBucket()),
        drive=FakeDrive() if drive is _DEFAULT else drive,
        open_source=open_source,
        temp=tmp_path,
        auth_url="https://auth.test",
        api_url="https://api.test",
        district=DistrictInfo(iddis="0197", s3_upload_host="mock-s3-host"),
        period=period_key(
            now.astimezone(settings.time_zone), settings.query_period_format
        ),
        opened_at=opened_at or now,
        schools=schools or [],
        roster_paths=roster_paths or {},
    )
