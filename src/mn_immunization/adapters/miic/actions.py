"""AISR bulk-query actions: roster upload, results listing, results download.

Errors carry an HTTP status and a short description of what was being
attempted, never the response body: bodies can echo request content, and
these messages reach logs. Retries key off the status, not message text.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from mn_immunization.workflow.ports import (
    RegistryError,
    RosterNotSentError,
    StagedResults,
)

logger = logging.getLogger(__name__)


class AISRActionFailedError(RegistryError):
    """An AISR call failed; `status_code` as for every RegistryError."""


@dataclass(frozen=True)
class DistrictInfo:
    """District-scoped values for the roster upload: the district's MDE
    number (`iddis`) and the MDH ingest bucket host. Configuration, never
    code: they were once hardcoded to ISD 197."""

    iddis: str
    s3_upload_host: str


@dataclass(frozen=True)
class SchoolQueryInformation:
    """One school's roster upload: AISR's upload metadata for the school
    plus the local path of the roster file being sent."""

    school_name: str
    classification: str
    school_id: str
    email_contact: str
    query_file_path: str


TRANSIENT_STATUSES = frozenset({502, 503, 504})


def _is_transient(error: BaseException) -> bool:
    if isinstance(
        error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
    ):
        return True
    return (
        isinstance(error, AISRActionFailedError)
        and error.status_code in TRANSIENT_STATUSES
    )


# Up to 5 attempts, exponential backoff 4-60s, on connection errors,
# timeouts, and 502/503/504. Applied only to calls with no side effects.
_transient_retry = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)


@dataclass
class S3UploadHeaders:
    """
    Dataclass to hold the headers required for S3 upload.
    """

    classification: str
    school_id: str
    email_contact: str
    iddis: str
    host: str
    content_type: str = "text/csv"


@_transient_retry
def _get_put_url(
    session: requests.Session,
    base_url: str,
    access_token: str,
    file_path: str,
    school_id: str,
) -> str:
    """Get the signed S3 URL for uploading the bulk query file.

    Retried like any read: signing has no side effects. MIIC emails the
    nurses on the roster *upload* (`_put_file_to_s3`), not on signing.
    """
    payload = json.dumps(
        {
            "filePath": file_path,
            "contentType": "text/csv",
            "schoolId": school_id,
        }
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    res = session.post(
        f"{base_url}/signing/puturl", headers=headers, data=payload, timeout=60
    )
    if res.status_code != 200:
        raise AISRActionFailedError(
            f"HTTP {res.status_code} requesting upload URL for school {school_id}",
            status_code=res.status_code,
        )
    try:
        body = res.json()
    except ValueError:
        raise AISRActionFailedError(
            f"unreadable upload-URL response for school {school_id}"
        ) from None
    url = body.get("url") if isinstance(body, dict) else None
    if not isinstance(url, str) or not url:
        raise AISRActionFailedError(f"no upload URL returned for school {school_id}")
    return url


def _put_file_to_s3(
    session: requests.Session, s3_url: str, headers: S3UploadHeaders, payload: bytes
) -> None:
    """Upload the roster file to S3 with the signed URL.

    Never retried: this upload is what makes MIIC email every nurse, and a
    timeout here leaves the outcome unknown. Retrying an unknown outcome
    risks a duplicate email; the run fails loudly instead.
    """
    headers_json = {
        "x-amz-meta-classification": headers.classification,
        "x-amz-meta-school_id": headers.school_id,
        "x-amz-meta-email_contact": headers.email_contact,
        "Content-Type": headers.content_type,
        "x-amz-meta-iddis": headers.iddis,
        "host": headers.host,
    }

    res = session.request("PUT", s3_url, headers=headers_json, data=payload, timeout=60)

    if res.status_code != 200:
        raise AISRActionFailedError(
            f"HTTP {res.status_code} uploading roster for school {headers.school_id}",
            status_code=res.status_code,
        )


@_transient_retry
def list_result_entries(
    session: requests.Session,
    base_url: str,
    access_token: str,
    school_id: str,
) -> list[dict]:
    """List the bulk-query result entries AISR holds for a school, oldest
    first (AISR's order)."""
    res = session.get(
        f"{base_url}/school/query/{school_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=120,
    )
    if res.status_code != 200:
        raise AISRActionFailedError(
            f"HTTP {res.status_code} listing results for school {school_id}",
            status_code=res.status_code,
        )
    try:
        entries = res.json()
    except ValueError:
        raise AISRActionFailedError(
            f"unreadable results listing for school {school_id}"
        ) from None
    return entries if isinstance(entries, list) else []


def _upload_time(entry: dict) -> datetime | None:
    """AISR's uploadDateTime is epoch milliseconds."""
    value = entry.get("uploadDateTime")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return None


def staged_results(
    session: requests.Session,
    base_url: str,
    access_token: str,
    school_id: str,
) -> StagedResults:
    """Whether the latest listed entry has a full results file, plus the
    listing's shape for the retention question."""
    entries = list_result_entries(session, base_url, access_token, school_id)
    times = [t for t in (_upload_time(e) for e in entries) if t is not None]
    return StagedResults(
        available=bool(entries and entries[-1].get("fullVaccineFileUrl")),
        entries=len(entries),
        newest_upload_at=max(times) if times else None,
    )


def get_latest_vaccination_records_url(
    session: requests.Session,
    base_url: str,
    access_token: str,
    school_id: str,
) -> str | None:
    """URL of the latest full vaccination records file, or None if AISR
    lists no results for the school."""
    entries = list_result_entries(session, base_url, access_token, school_id)
    if not entries:
        return None
    return entries[-1].get("fullVaccineFileUrl")


@_transient_retry
def download_vaccination_records(session: requests.Session, file_url: str) -> str:
    """Download a vaccination records file; returns its text."""
    res = session.get(file_url, timeout=300)

    if res.status_code != 200:
        raise AISRActionFailedError(
            f"HTTP {res.status_code} downloading results file",
            status_code=res.status_code,
        )
    return res.content.decode("utf-8")


def get_and_download_vaccination_records(
    session: requests.Session,
    access_token: str,
    base_url: str,
    school_id: str,
) -> str:
    """Download the latest results file for a school; returns its text.
    Raises AISRActionFailedError if none is listed."""
    url = get_latest_vaccination_records_url(
        session=session,
        base_url=base_url,
        access_token=access_token,
        school_id=school_id,
    )
    if not url:
        raise AISRActionFailedError(
            f"No vaccination records available for school ID {school_id}"
        )
    return download_vaccination_records(session=session, file_url=url)


def bulk_query_aisr(
    session: requests.Session,
    access_token: str,
    base_url: str,
    query_info: SchoolQueryInformation,
    district: DistrictInfo,
) -> None:
    """Submit one school's roster as a bulk query: read, sign, then upload.

    Everything that can fail without MIIC receiving anything happens
    first, and raises RosterNotSentError: the caller may safely release its
    claim and let a rerun try again. The upload itself is never retried
    and its failures are not RosterNotSentError: by then the outcome is
    unknown. The local file path is sent as `filePath` to MDH signing, as
    it always has been; MDH accepts it.
    """
    try:
        payload = Path(query_info.query_file_path).read_bytes()
        signed_s3_url = _get_put_url(
            session,
            base_url,
            access_token,
            query_info.query_file_path,
            query_info.school_id,
        )
    except Exception as error:
        raise RosterNotSentError(
            f"roster for school {query_info.school_id} not sent "
            f"({type(error).__name__} before upload)",
            status_code=getattr(error, "status_code", None),
        ) from error
    _put_file_to_s3(
        session,
        signed_s3_url,
        S3UploadHeaders(
            classification=query_info.classification,
            school_id=query_info.school_id,
            email_contact=query_info.email_contact,
            iddis=district.iddis,
            host=district.s3_upload_host,
        ),
        payload,
    )
