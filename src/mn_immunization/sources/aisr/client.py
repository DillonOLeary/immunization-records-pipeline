"""Session-scoped AISR client: the ImmunizationSource implementation.

A context manager owns the login/logout lifecycle, and the client exposes
the operations the pipeline performs. Retry behavior lives on the
underlying action functions; parsing lives in `parsing.py`, so AISR's
file format never leaves this package.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import requests

from mn_immunization.domain.hashing import sha256_hex
from mn_immunization.sources.aisr.actions import (
    bulk_query_aisr,
    get_and_download_vaccination_records,
    staged_results,
)
from mn_immunization.sources.aisr.authenticate import login, logout
from mn_immunization.sources.aisr.parsing import parse_aisr_csv
from mn_immunization.sources.aisr.port import (
    DistrictInfo,
    FetchedRecords,
    SchoolQueryInformation,
    SourceOpener,
    StagedResults,
)

logger = logging.getLogger(__name__)


@dataclass
class AisrClient:
    session: requests.Session
    api_base_url: str
    access_token: str

    def submit_roster_query(
        self, school: SchoolQueryInformation, district: DistrictInfo
    ) -> None:
        """Upload a school's roster query file to AISR."""
        bulk_query_aisr(
            self.session, self.access_token, self.api_base_url, school, district
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
    auth_base_url: str, api_base_url: str, username: str, password: str
) -> Iterator[AisrClient]:
    """Log into AISR, yield a client, and always try to log out.

    A failed logout is logged and swallowed: raising from `finally` would
    replace whatever error the body raised, and that error is the one the
    run needs to record.
    """
    with requests.Session() as session:
        auth = login(session, auth_base_url, username, password)
        try:
            yield AisrClient(
                session=session,
                api_base_url=api_base_url,
                access_token=auth.access_token,
            )
        finally:
            try:
                logout(session, auth_base_url)
            except Exception as error:
                logger.warning("AISR logout failed (%s)", type(error).__name__)


def aisr_opener(secret: Callable[[str], str]) -> SourceOpener:
    """A SourceOpener that logs in with the AISR credentials from
    `secret` (a secret name -> value reader), read when first needed and
    kept for the run. The credentials stay inside this adapter."""
    credentials: list[str] = []

    def open_source(auth_url: str, api_url: str):
        if not credentials:
            credentials.extend([secret("aisr-username"), secret("aisr-password")])
        username, password = credentials
        return aisr_session(auth_url, api_url, username, password)

    return open_source
