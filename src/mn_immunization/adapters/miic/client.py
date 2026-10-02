"""MIIC through AISR's bulk interface: the workflow's Registry, session-scoped.

A context manager owns the login/logout lifecycle; the client exposes the
operations the workflow performs. Endpoints, credentials, the district's
upload identity, and each school's upload metadata are bound in by
composition, so none of them reach the workflow. Retry behavior lives on the
action functions; parsing lives in `parsing.py`, so AISR's file formats
never leave this package.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import requests

from mn_immunization.adapters.miic.actions import (
    DistrictInfo,
    SchoolQueryInformation,
    bulk_query_aisr,
    get_and_download_vaccination_records,
    staged_results,
)
from mn_immunization.adapters.miic.authenticate import login, logout
from mn_immunization.adapters.miic.parsing import parse_aisr_csv
from mn_immunization.records.hashing import sha256_hex
from mn_immunization.workflow.ports import (
    FetchedRecords,
    RegistryOpener,
    RosterNotSentError,
    School,
    StagedResults,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchoolUpload:
    """AISR's upload metadata for one school (from config)."""

    classification: str
    email_contact: str


@dataclass
class AisrClient:
    session: requests.Session
    api_base_url: str
    access_token: str
    district: DistrictInfo
    uploads: Mapping[str, SchoolUpload]  # school id -> its upload metadata
    temp: Path

    def submit_roster(self, school: School, roster: str) -> None:
        """Upload a school's roster as a bulk query. The roster is written
        to a local file first because MDH signing has always been sent the
        file's path as `filePath`."""
        try:
            upload = self.uploads[school.id]
            path = self.temp / f"{school.name}_query.csv"
            path.write_text(roster, encoding="utf-8")
        except Exception as error:
            raise RosterNotSentError(
                f"roster for school {school.id} not sent "
                f"({type(error).__name__} before upload)"
            ) from error
        bulk_query_aisr(
            self.session,
            self.access_token,
            self.api_base_url,
            SchoolQueryInformation(
                school_name=school.name,
                classification=upload.classification,
                school_id=school.id,
                email_contact=upload.email_contact,
                query_file_path=str(path),
            ),
            self.district,
        )

    def staged_results(self, school_id: str) -> StagedResults:
        """Read-only: what AISR lists for the school right now."""
        return staged_results(
            self.session, self.api_base_url, self.access_token, school_id
        )

    def fetch_latest_records(self, school_id: str) -> FetchedRecords:
        """Download and parse the school's latest full results file.

        Raises AISRActionFailedError if none is listed, AisrParseError if
        the file cannot be parsed (a MIIC format change lands here).
        """
        text = get_and_download_vaccination_records(
            session=self.session,
            access_token=self.access_token,
            base_url=self.api_base_url,
            school_id=school_id,
        )
        return FetchedRecords(
            records=parse_aisr_csv(text),
            content_hash=sha256_hex(text),
            byte_size=len(text.encode("utf-8")),
        )


@contextmanager
def aisr_session(
    auth_base_url: str,
    api_base_url: str,
    username: str,
    password: str,
    district: DistrictInfo,
    uploads: Mapping[str, SchoolUpload],
) -> Iterator[AisrClient]:
    """Log into AISR, yield a client, and always try to log out.

    A failed logout is logged and swallowed: raising from `finally` would
    replace whatever error the body raised, and that error is the one the
    run needs to record.
    """
    with requests.Session() as session, tempfile.TemporaryDirectory() as temp:
        auth = login(session, auth_base_url, username, password)
        try:
            yield AisrClient(
                session=session,
                api_base_url=api_base_url,
                access_token=auth.access_token,
                district=district,
                uploads=uploads,
                temp=Path(temp),
            )
        finally:
            try:
                logout(session, auth_base_url)
            except Exception as error:
                logger.warning("AISR logout failed (%s)", type(error).__name__)


def aisr_opener(
    secret: Callable[[str], str],
    auth_url: str,
    api_url: str,
    district: DistrictInfo,
    uploads: Mapping[str, SchoolUpload],
) -> RegistryOpener:
    """A RegistryOpener bound to this district's AISR endpoints and upload
    identity, logging in with the MIIC account's credentials from `secret` (a secret
    name -> value reader), read when first needed and kept for the run."""
    credentials: list[str] = []

    def open_registry():
        if not credentials:
            credentials.extend([secret("miic-username"), secret("miic-password")])
        username, password = credentials
        return aisr_session(auth_url, api_url, username, password, district, uploads)

    return open_registry
