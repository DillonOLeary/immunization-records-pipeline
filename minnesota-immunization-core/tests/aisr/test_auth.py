"""
Integration tests for authentication and authorization.
"""

# pylint: disable=missing-function-docstring

from unittest.mock import Mock

import requests

from minnesota_immunization_core.aisr.authenticate import (
    AuthenticationError,
    _get_access_token_using_response_code,
    _get_code_from_response,
    login,
    logout,
)

TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"
TEST_ROW_ID = "test_row_id"


def test_request_access_token_with_code(fastapi_server):
    auth_base_url = f"{fastapi_server}/mock-auth-server"

    with requests.Session() as local_session:
        token = _get_access_token_using_response_code(
            local_session, auth_base_url, "test_code"
        )

    assert token == "mocked-access-token", "Access token should be returned"


def test_extract_code_from_auth_response_headers(fastapi_server):
    auth_base_url = f"{fastapi_server}/mock-auth-server"

    mock_response = Mock()
    mock_response.status_code = 302
    mock_response.headers = {"Location": f"{auth_base_url}#code=test_code"}

    code = _get_code_from_response(mock_response)

    assert code == "test_code", "Code should be extracted from the Location header"


def test_login_successful(fastapi_server):
    auth_base_url = f"{fastapi_server}/mock-auth-server"

    with requests.Session() as local_session:
        login_result = login(
            session=local_session,
            base_url=auth_base_url,
            username=TEST_USERNAME,
            password=TEST_PASSWORD,
        )
    assert login_result.access_token, "Log in should return an access token"


def test_login_failure(fastapi_server):
    auth_base_url = f"{fastapi_server}/mock-auth-server"

    with requests.Session() as local_session:
        try:
            login(
                session=local_session,
                base_url=auth_base_url,
                username=TEST_USERNAME,
                password="wrong_password",
            )
            raise AssertionError(
                "Login should raise an exception with invalid credentials"
            )
        except AuthenticationError as e:
            assert "Login failed" in str(e), "Exception should mention login failure"
            assert "Invalid credentials" in str(e), (
                "Exception should mention invalid credentials"
            )


def test_logout_successful(fastapi_server):
    auth_base_url = f"{fastapi_server}/mock-auth-server"

    with requests.Session() as local_session:
        login(
            session=local_session,
            base_url=auth_base_url,
            username=TEST_USERNAME,
            password=TEST_PASSWORD,
        )
        logout(local_session, auth_base_url)
    assert not local_session.cookies, "Session cookies should be cleared after logout"
