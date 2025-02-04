"""
Tests for interacting with AISR
"""

# pylint: disable=missing-function-docstring

from unittest.mock import Mock

import requests
from data_pipeline.aisr import (
    S3UploadHeaders,
    _get_access_token_using_response_code,
    _get_code_from_response,
    _get_put_url,
    put_file_to_s3,
)

UPLOAD_FILE_NAME = "test_file.csv"


def test_request_access_token_with_code(fastapi_server):
    test_realm_url = f"{fastapi_server}/auth/realms/idepc-aisr-realm"

    with requests.Session() as local_session:
        token = _get_access_token_using_response_code(
            local_session, test_realm_url, "test_code"
        )

    assert token == "mocked-access-token", "Access token should be returned"


def test_extract_code_from_auth_response_headers(fastapi_server):
    test_realm_url = f"{fastapi_server}/auth/realms/idepc-aisr-realm"
    mock_response = Mock()
    mock_response.status_code = 302
    mock_response.headers = {"Location": f"{test_realm_url}#code=test_code"}

    code = _get_code_from_response(mock_response)

    assert code == "test_code", "Code should be extracted from the Location header"


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
