"""Session-scoped AISR client.

Replaces the closure-factory workflow builders: a context manager owns the
login/logout lifecycle, and the client exposes the two operations the
pipeline performs. Retry behavior lives on the underlying action functions.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import requests

from mn_immunization.sources.aisr.actions import (
    SchoolQueryInformation,
    bulk_query_aisr,
    get_and_download_vaccination_records,
)
from mn_immunization.sources.aisr.authenticate import login, logout


@dataclass
class AisrClient:
    session: requests.Session
    api_base_url: str
    access_token: str

    def submit_roster_query(self, school: SchoolQueryInformation) -> None:
        """Upload a school's roster query file to AISR."""
        bulk_query_aisr(
            self.session, self.access_token, self.api_base_url, school
        )

    def download_latest_records(self, school_id: str, output_path: Path) -> str:
        """Download the latest full vaccination records file for a school.

        Writes the raw AISR file to output_path and returns its content.
        Raises AISRActionFailedError if no records are available.
        """
        response = get_and_download_vaccination_records(
            session=self.session,
            access_token=self.access_token,
            base_url=self.api_base_url,
            school_id=school_id,
            output_path=output_path,
        )
        return response.content or ""


@contextmanager
def aisr_session(
    auth_base_url: str, api_base_url: str, username: str, password: str
) -> Iterator[AisrClient]:
    """Log into AISR, yield a client, and always log out."""
    with requests.Session() as session:
        auth = login(session, auth_base_url, username, password)
        try:
            yield AisrClient(
                session=session,
                api_base_url=api_base_url,
                access_token=auth.access_token,
            )
        finally:
            logout(session, auth_base_url)
