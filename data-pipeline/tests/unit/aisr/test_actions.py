"""
Tests for interacting with AISR
"""

# pylint: disable=missing-function-docstring

import pytest
import requests
from data_pipeline.aisr.actions import (
    AISRActionFailedException,
    S3UploadHeaders,
    _get_put_url,
    _put_file_to_s3,
    bulk_query_aisr,
)
from data_pipeline.pipeline_factory import SchoolQueryInformation

UPLOAD_FILE_NAME = "test_file.csv"


def test_can_get_put_url(fastapi_server):

    with requests.Session() as local_session:
        url = _get_put_url(
            local_session, fastapi_server, "test_access_token", "test-file.csv", 1234
        )

    assert url == f"{fastapi_server}/test-s3-put-location", "URL should be returned"


def test_upload_file_to_s3(fastapi_server, tmp_path):
    test_url = f"{fastapi_server}/test-s3-put-location"
    test_file_name = tmp_path / UPLOAD_FILE_NAME
    with open(test_file_name, "w", encoding="utf-8") as file:
        file.write("test data")

    test_headers = S3UploadHeaders("", "", "", "", "", "")

    with requests.Session() as local_session:
        response = _put_file_to_s3(
            local_session, test_url, test_headers, test_file_name
        )

    assert response.is_successful, "File upload should be successful"


def test_failed_upload_raises_exception(fastapi_server, tmp_path):
    test_url = f"{fastapi_server}/test-s3-put-location"
    test_file_name = tmp_path / UPLOAD_FILE_NAME
    with open(test_file_name, "w", encoding="utf-8") as file:
        file.write("")

    test_headers = S3UploadHeaders("", "", "", "", "", "")

    with requests.Session() as local_session:
        with pytest.raises(AISRActionFailedException):
            _put_file_to_s3(local_session, test_url, test_headers, test_file_name)


def test_complete_query_action(fastapi_server, tmp_path):
    test_file_name_and_path = tmp_path / UPLOAD_FILE_NAME
    with open(test_file_name_and_path, "w", encoding="utf-8") as file:
        file.write("test data")

    with requests.Session() as local_session:
        response = bulk_query_aisr(
            session=local_session,
            access_token="mocked-access-token",
            base_url=fastapi_server,
            query_info=SchoolQueryInformation(
                "name", "class", "id", "email@example.com", str(test_file_name_and_path)
            ),
        )

    assert response.is_successful, "File upload should be successful"
