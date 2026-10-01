"""Session-scoped AISR client.

Replaces the closure-factory workflow builders: a context manager owns the
login/logout lifecycle, and the client exposes the operations the
pipeline performs. Retry behavior lives on the underlying action functions.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import requests

from mn_immunization.sources.aisr.actions import (
    DistrictInfo,
    SchoolQueryInformation,
    StagedResults,
    bulk_query_aisr,
    get_and_download_vaccination_records,
    staged_results,
)
from mn_immunization.sources.aisr.authenticate import login, logout

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

    def download_latest_records(self, school_id: str, output_path: Path) -> str:
        """Download the latest full vaccination records file for a school.

        Writes the raw AISR file to output_path and returns its content.
        Raises AISRActionFailedError if no records are available.
        """
        return get_and_download_vaccination_records(
            session=self.session,
            access_token=self.access_token,
            base_url=self.api_base_url,
            school_id=school_id,
            output_path=output_path,
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
