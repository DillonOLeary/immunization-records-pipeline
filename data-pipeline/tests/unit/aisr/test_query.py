"""
Tests for interacting with AISR
"""

# pylint: disable=missing-function-docstring

import requests
from data_pipeline.aisr.query import S3UploadHeaders, _get_put_url, put_file_to_s3

UPLOAD_FILE_NAME = "test_file.csv"


def test_can_get_put_url(fastapi_server):
    test_url = f"{fastapi_server}/signing/puturl"

    with requests.Session() as local_session:
        url = _get_put_url(
            local_session, test_url, "test_access_token", "test-file.csv", 1234
        )

    assert url == f"{fastapi_server}/test-put-location", "URL should be returned"


def test_upload_file_to_s3(fastapi_server, tmp_path):
    test_url = f"{fastapi_server}/test-s3-put-location"
    test_file_name = tmp_path / UPLOAD_FILE_NAME
    with open(test_file_name, "w", encoding="utf-8") as file:
        file.write("test data")

    test_headers = S3UploadHeaders("", "", "", "", "", "")

    with requests.Session() as local_session:
        response = put_file_to_s3(local_session, test_url, test_headers, test_file_name)

    assert response.is_successful, "File upload should be successful"
