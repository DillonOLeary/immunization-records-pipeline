"""Ports: everything the workflow needs from outside, in its own words.

The workflow (policy, steps, cycles) talks only to these. Each adapter under
`adapters/` implements them for one external system, and
`runtime/composition.py` wires them up. Nothing here names a technology:
another registry, delivery target, or store slots in behind the same
Protocol without touching the workflow.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mn_immunization.records.model import RecordSet
from mn_immunization.workflow.events import LedgerEvent

# --- the district's schools, and the registry they are queried in (MIIC) ---


@dataclass(frozen=True)
class School:
    """A school whose roster goes to the registry each period."""

    id: str
    name: str


class RegistryError(Exception):
    """A registry call failed. `status_code` is the HTTP status when there
    was a response, None otherwise. The message never includes a body."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RosterNotSentError(RegistryError):
    """A roster submission failed before anything was uploaded, so the
    registry received nothing and emailed no one. The one failure after
    which a retry is safe."""


@dataclass(frozen=True)
class StagedResults:
    """What the registry lists for one school. `available` is the staging
    signal; `newest_upload_at` is what tells this period's results from a
    previous period's, which the registry keeps listing for days."""

    available: bool
    entries: int
    newest_upload_at: datetime | None


@dataclass(frozen=True)
class FetchedRecords:
    """A school's latest results, parsed. The hash and size describe the
    raw file, for the ledger; the records are the only content."""

    records: RecordSet
    content_hash: str
    byte_size: int


class Registry(Protocol):
    """A logged-in registry session. The registry owns its file formats:
    rosters go in as text, results come back as records."""

    def submit_roster(self, school: School, roster: str) -> None:
        """Send a school's roster. In MIIC this emails every nurse. Raises
        RosterNotSentError if it failed before anything was uploaded; any
        other error leaves the outcome unknown."""
        ...

    def staged_results(self, school_id: str) -> StagedResults:
        """Read-only: what the registry lists for the school now."""
        ...

    def fetch_latest_records(self, school_id: str) -> FetchedRecords:
        """The school's latest full results, parsed. Raises if none are
        listed or the file cannot be parsed."""
        ...


RegistryOpener = Callable[[], AbstractContextManager[Registry]]
"""Opens a logged-in session that logs out on exit. Endpoints and
credentials are bound in by composition; the workflow never holds them."""


# --- the student information system rosters come from (Infinite Campus) ---


class RosterSource(Protocol):
    """A logged-in session with the student information system."""

    def export_roster(self, school_id: str) -> str:
        """The school's current roster, in the layout the registry takes
        (`records.roster`). Read-only."""
        ...


RosterSourceOpener = Callable[[], AbstractContextManager[RosterSource]]


@dataclass(frozen=True)
class District:
    """The district as its config describes it, bound to its adapters.
    `open_rosters` is None when rosters are uploaded by hand instead."""

    schools: tuple[School, ...]
    open_registry: RegistryOpener
    open_rosters: RosterSourceOpener | None = None


# --- delivery: where new records go for import into Infinite Campus ---


class Delivery(Protocol):
    """The import queue (a Drive folder today). Uploading fills it; staff
    delete a file once it is imported, so listing shows what is pending."""

    def upload(self, name: str, text: str) -> str:
        """Upload `text` as file `name`; returns the remote file id."""
        ...

    def list_filenames(self) -> set[str]:
        """Names of the files this app has in the queue right now."""
        ...


# --- the district's object store: config, rosters, the known set ---


class ObjectNotFoundError(Exception):
    """No object at that path. The message is the path, never content."""


class ObjectStore(Protocol):
    def read_text(self, path: str) -> str:
        """The object's text; raises ObjectNotFoundError if absent."""
        ...

    def write_text(
        self, path: str, text: str, content_type: str = "text/plain"
    ) -> None: ...


# --- the run ledger ---


class RunLedger(Protocol):
    def append(self, event: LedgerEvent) -> None: ...

    def claim(self, key: str) -> bool:
        """Atomically claim a key. True exactly once per key, across runs."""
        ...

    def release(self, key: str) -> None:
        """Give back a claim this run won, only if it is unchanged since.
        For the one case where the guarded action provably never started."""
        ...

    def recent_runs(self, months: int = 2, limit: int | None = None) -> list[dict]:
        """Recent runs (this run included), newest first: dicts of run_id
        and events, each event the stored envelope (type, data, at, ...)."""
        ...

    def held_claims(self, prefix: str) -> dict[str, dict]:
        """Claims whose key starts with prefix: key -> claimant payload."""
        ...
