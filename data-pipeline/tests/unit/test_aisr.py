"""
Tests for interacting with AISR
"""

# pylint: disable=missing-function-docstring

from unittest.mock import Mock

import requests
from data_pipeline.aisr import (
    _get_access_token_using_response_code,
    _get_code_from_response,
)


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
    mock_response.headers = {"Location": f"{test_realm_url}?code=test_code"}

    code = _get_code_from_response(mock_response)

    assert code == "test_code", "Code should be extracted from the Location header"
