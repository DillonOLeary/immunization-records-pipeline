"""Port for immunization record sources, and the vocabulary it speaks.

AisrClient (behind `aisr_session`) is today's implementation. A second
source (another state registry, a different bulk interface after MIIC's
website change) implements ImmunizationSource and slots into the
composition root without touching the pipeline.

The source owns its file format: `fetch_latest_records` returns parsed
records, so AISR's pipe-delimited layout never leaves `sources/aisr/`.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mn_immunization.domain.records import RecordSet


class AISRActionFailedError(Exception):
    """An AISR call failed. `status_code` is the HTTP status when there
    was a response, None otherwise. The message never includes a body."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class QueryNotSentError(AISRActionFailedError):
    """A roster submission failed before its upload began (the roster file
    could not be read, or signing failed), so MIIC received nothing and
    emailed no one. The one failure after which a retry is safe."""


@dataclass
class DistrictInfo:
    """District-scoped values for the roster upload.

    Both were once hardcoded to ISD 197; they are configuration now so a
    second district needs no code change. `iddis` is the district's MDE
    number; `s3_upload_host` is the MDH ingest bucket host (the same for
    every district today, but environment-shaped, so it lives in config
    rather than in code).
    """

    iddis: str
    s3_upload_host: str


@dataclass
class SchoolQueryInformation:
    """One school, as config describes it, plus the local path of its
    roster file for this run."""

    school_name: str
    classification: str
    school_id: str
    email_contact: str
    query_file_path: str


@dataclass(frozen=True)
class StagedResults:
    """What the source lists for one school. `available` is the staging
    signal the pipeline acts on; `entries` and `newest_upload_at` are
    recorded only to learn whether AISR keeps old results between runs
    (if it does, "any result listed" is not "staged for this period")."""

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


class ImmunizationSource(Protocol):
    """A logged-in session with the registry."""

    def submit_roster_query(
        self, school: SchoolQueryInformation, district: DistrictInfo
    ) -> None:
        """Send a school's roster. In MIIC this emails every nurse. Raises
        QueryNotSentError if it failed before anything was uploaded; any
        other error leaves the outcome unknown."""
        ...

    def staged_results(self, school_id: str) -> StagedResults:
        """Read-only: what the registry lists for the school now."""
        ...

    def fetch_latest_records(self, school_id: str) -> FetchedRecords:
        """The school's latest full results, parsed. Raises if none are
        listed or the file cannot be parsed."""
        ...


SourceOpener = Callable[[str, str], AbstractContextManager[ImmunizationSource]]
"""(auth_url, api_url) -> a logged-in session that logs out on exit.
Credentials are the opener's business; the pipeline never holds them."""
