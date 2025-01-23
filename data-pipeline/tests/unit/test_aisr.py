"""
Tests for interacting with AISR
"""

# pylint: disable=missing-function-docstring

import requests
from data_pipeline.aisr import login, logout

TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"
TEST_ROW_ID = "test_row_id"


def test_login_successful(fastapi_server):
    test_realm_url = f"{fastapi_server}/auth/realms/idepc-aisr-realm"

    with requests.Session() as local_session:
        result = login(
            session=local_session,
            auth_realm_url=test_realm_url,
            username=TEST_USERNAME,
            password=TEST_PASSWORD,
        )
    assert result.is_successful, "Log in should be successful"


def test_login_failure(fastapi_server):
    test_realm_url = f"{fastapi_server}/auth/realms/idepc-aisr-realm"

    with requests.Session() as local_session:
        result = login(
            session=local_session,
            auth_realm_url=test_realm_url,
            username=TEST_USERNAME,
            password="wrong_password",
        )
    assert not result.is_successful, "Log in should fail with incorrect password"


def test_logout_successful(fastapi_server):
    test_realm_url = f"{fastapi_server}/auth/realms/idepc-aisr-realm"

    with requests.Session() as local_session:
        login(
            session=local_session,
            auth_realm_url=test_realm_url,
            username=TEST_USERNAME,
            password=TEST_PASSWORD,
        )
        logout(local_session, test_realm_url)
    assert not local_session.cookies, "Session cookies should be cleared after logout"
