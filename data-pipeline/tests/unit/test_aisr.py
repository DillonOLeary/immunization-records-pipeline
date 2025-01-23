"""
Tests for interacting with AISR
"""

# pylint: disable=missing-function-docstring

# import uuid
# from getpass import getpass
# from typing import Tuple
# from urllib.parse import parse_qs, quote, urlparse

import requests

# from bs4 import BeautifulSoup
from data_pipeline.aisr import login, logout

TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"
TEST_ROW_ID = "test_row_id"


# def get_session_and_tab(s: requests.Session) -> Tuple[str, str]:
#     state = uuid.uuid4()
#     nonce = uuid.uuid4()

#     url = f"https://authenticator4.web.health.state.mn.us/auth/realms/idepc-aisr-realm/protocol/openid-connect/auth?client_id=aisr-app&redirect_uri=https%3A%2F%2Faisr.web.health.state.mn.us%2Fhome&state={state}&response_mode=fragment&response_type=code&scope=openid&nonce={nonce}"

#     payload = {}
#     headers = {}
#     response = s.request("GET", url, headers=headers, data=payload)
#     soup = BeautifulSoup(response.content, "html.parser")
#     form_element = soup.find("form", id="kc-form-login")
#     action_url = form_element.get("action") if form_element else None
#     parsed_url = urlparse(action_url)
#     query_dict = parse_qs(parsed_url.query)

#     return query_dict["session_code"][0], query_dict["tab_id"][0]


# def authenticate(s: requests.Session):
#     url = f"https://authenticator4.web.health.state.mn.us/auth/realms/idepc-aisr-realm/login-actions/authenticate?session_code={session_code}&execution=084dee30-925f-4a8f-829d-7a372e38d0de&client_id=aisr-app&tab_id={tab_id}"

#     password = getpass()
#     payload = f"password={quote(password)}&username=dave.sandum%40isd197.org"
#     headers = {"Content-Type": "application/x-www-form-urlencoded"}

#     response = s.request("POST", url, headers=headers, data=payload)
#     print(response.text)


# with requests.Session() as session:
#     session_code, tab_id = get_session_and_tab(session)
#     authenticate(session)
#     print(session.cookies)
#     OPTIONS_URL = "https://aisr-api.web.health.state.mn.us/school/list/public"

#     res = session.request("GET", OPTIONS_URL, headers={}, data={})
#     print(res.text)


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
