"""
Module for query interactions with AISR
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class AISRActionFailedError(Exception):
    """Custom exception for AISR failures."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_put_url(
    session: requests.Session,
    base_url: str,
    access_token: str,
    file_path: str,
    school_id: str,
) -> str:
    """
    Get the the signed S3 URL for uploading the bulk query file.
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

    json_string = res.content.decode("utf-8")
    return json.loads(json_string).get("url")


@dataclass
class S3UploadHeaders:
    """
    Dataclass to hold the headers required for S3 upload.
    # TODO some fields are hard coded to isd 197
    """

    classification: str
    school_id: str
    email_contact: str
    content_type: str = "text/csv"
    iddis: str = "0197"
    host: str = (
        "mdh-aisr-immunization-ingest-us-east-2-100582527228.s3.us-east-2.amazonaws.com"
    )


@dataclass
class AISRFileUploadResponse:
    """
    Dataclass to hold the response from the file upload.
    """

    is_successful: bool
    message: str


@dataclass
class AISRFileDownloadResponse:
    """
    Dataclass to hold the response from the file download.
    """

    is_successful: bool
    message: str
    content: str | None = None


def _put_file_to_s3(
    session: requests.Session, s3_url: str, headers: S3UploadHeaders, file_name: str
) -> AISRFileUploadResponse:
    """
    Upload a file to S3 with signed url and the specified headers.
    """
    headers_json = {
        "x-amz-meta-classification": headers.classification,
        "x-amz-meta-school_id": headers.school_id,
        "x-amz-meta-email_contact": headers.email_contact,
        "Content-Type": headers.content_type,
        "x-amz-meta-iddis": headers.iddis,
        "host": headers.host,
    }

    with open(file_name, "rb") as file:
        payload = file.read()

    res = session.request("PUT", s3_url, headers=headers_json, data=payload, timeout=60)

    if res.status_code == 200:
        return AISRFileUploadResponse(
            is_successful=True,
            message="File uploaded successfully",
        )
    raise AISRActionFailedError(
        f"Failed to upload file: {res.status_code} - {res.text}"
    )


@dataclass
class SchoolQueryInformation:
    """
    Class to hold the information needed to query a school.
    """

    school_name: str
    classification: str
    school_id: str
    email_contact: str
    query_file_path: str


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=(
        retry_if_exception_type(
            (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
        )
        | retry_if_exception(
            lambda e: isinstance(e, AISRActionFailedError)
            and any(code in str(e) for code in ["502", "503", "504"])
        )
    ),
    reraise=True,
)
def get_latest_vaccination_records_url(
    session: requests.Session,
    base_url: str,
    access_token: str,
    school_id: str,
) -> str | None:
    """
    Get the URL for the latest full vaccination records file.

    This function fetches the list of vaccination records for a school
    and returns the URL for the most recent full vaccination file.

    Returns None if no records are available.

    Retries up to 5 times with exponential backoff (4-60s) on:
    - Connection/timeout errors
    - HTTP 502/503/504 server errors
    """
    url = f"{base_url}/school/query/{school_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    res = session.get(url, headers=headers, timeout=120)

    if res.status_code != 200:
        raise AISRActionFailedError(
            f"Failed to get vaccination records: {res.status_code} - {res.text}"
        )

    records_list = json.loads(res.content.decode("utf-8"))

    # Get the latest record URL
    if not records_list or len(records_list) == 0:
        return None

    # Get the last (most recent) record
    latest_record = records_list[-1]
    return latest_record.get("fullVaccineFileUrl")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=(
        retry_if_exception_type(
            (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
        )
        | retry_if_exception(
            lambda e: isinstance(e, AISRActionFailedError)
            and any(code in str(e) for code in ["502", "503", "504"])
        )
    ),
    reraise=True,
)
def download_vaccination_records(
    session: requests.Session, file_url: str, output_path: Path
) -> AISRFileDownloadResponse:
    """
    Download a vaccination records file from the provided URL
    and save it to the specified path.

    Returns a response indicating success or failure.

    Retries up to 5 times with exponential backoff (4-60s) on:
    - Connection/timeout errors
    - HTTP 502/503/504 server errors
    """
    res = session.get(file_url, timeout=300)

    if res.status_code != 200:
        raise AISRActionFailedError(
            f"Failed to download file: {res.status_code} - {res.text}"
        )

    content = res.content.decode("utf-8")
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(content)

    return AISRFileDownloadResponse(
        is_successful=True,
        message=f"File downloaded successfully to {output_path}",
        content=content,
    )


def get_and_download_vaccination_records(
    session: requests.Session,
    access_token: str,
    base_url: str,
    school_id: str,
    output_path: Path,
) -> AISRFileDownloadResponse:
    """
    Get the latest vaccination records URL and download the file to the specified path.

    Args:
        session: Requests session with authentication
        access_token: AISR access token
        base_url: AISR API base URL
        school_id: School ID to get vaccination records for
        output_path: Path to save the downloaded file

    Returns:
        AISRFileDownloadResponse containing success status and message
    """
    # Get the URL for the latest vaccination records
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

    # Download the file
    return download_vaccination_records(
        session=session, file_url=url, output_path=output_path
    )


def bulk_query_aisr(
    session: requests.Session,
    access_token: str,
    base_url: str,
    query_info: SchoolQueryInformation,
) -> AISRFileUploadResponse:
    """
    Perform a bulk query to AISR.
    """
    if query_info.query_file_path is None:
        raise AISRActionFailedError("Query file path is not set.")
    signed_s3_url = _get_put_url(
        session,
        base_url,
        access_token,
        query_info.query_file_path,
        query_info.school_id,
    )
    _put_file_to_s3(
        session,
        signed_s3_url,
        S3UploadHeaders(
            classification=query_info.classification,
            school_id=query_info.school_id,
            email_contact=query_info.email_contact,
        ),
        query_info.query_file_path,
    )
    return AISRFileUploadResponse(
        is_successful=True, message="File uploaded successfully"
    )
