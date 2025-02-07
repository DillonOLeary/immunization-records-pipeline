"""
Module for query interactions with AISR
"""

import json
import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


class AISRActionFailedException(Exception):
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
    raise AISRActionFailedException(
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
    query_file_path: str | None = None


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
        raise AISRActionFailedException("Query file path is not set.")
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
