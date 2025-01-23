"""
Query MIIC for school immunization data
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Tuple
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


def _get_session_and_tab(
    session: requests.Session, auth_realm_url: str
) -> Tuple[str, str]:
    """
    The session and tab are needed to authenticate with AISR.
    """
    state = uuid.uuid4()
    nonce = uuid.uuid4()

    # pylint: disable-next=line-too-long
    url = f"{auth_realm_url}/protocol/openid-connect/auth?client_id=aisr-app&redirect_uri=https%3A%2F%2Faisr.web.health.state.mn.us%2Fhome&state={state}&response_mode=fragment&response_type=code&scope=openid&nonce={nonce}"

    response = session.request("GET", url, headers={}, data={})
    soup = BeautifulSoup(response.content, "html.parser")
    form_element = soup.find("form", id="kc-form-login")

    if isinstance(form_element, Tag):
        action_url = form_element.get("action")
        if isinstance(action_url, str):
            parsed_url = urlparse(action_url)
            query_dict = parse_qs(parsed_url.query)
            print(query_dict["session_code"][0], query_dict["tab_id"][0])
            return query_dict["session_code"][0], query_dict["tab_id"][0]
        raise ValueError("The action URL is not a valid string.")
    raise ValueError("Login form not found or is not a valid HTML form element.")


@dataclass
class AISRResponse:
    """
    Dataclass to hold the response from interactions with AISR.
    """

    is_successful: bool
    message: str


def login(
    session: requests.Session, auth_realm_url: str, username: str, password: str
) -> AISRResponse:
    """
    Login with AISR.
    """
    logger.info("Logging into MIIC")
    session_code, tab_id = _get_session_and_tab(session, auth_realm_url)

    # pylint: disable-next=line-too-long
    url = f"{auth_realm_url}/login-actions/authenticate?session_code={session_code}&execution=084dee30-925f-4a8f-829d-7a372e38d0de&client_id=aisr-app&tab_id={tab_id}"

    payload = f"password={quote(password)}&username={username}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = session.request("POST", url, headers=headers, data=payload)

    if response.status_code == 200 and "KEYCLOAK_IDENTITY" in response.cookies:
        logger.info("Logged in successfully")
        return AISRResponse(is_successful=True, message="Logged in successfully")

    logger.error("Login failed or KEYCLOAK_IDENTITY cookie is missing")
    return AISRResponse(
        is_successful=False,
        message="Login failed or KEYCLOAK_IDENTITY cookie is missing",
    )


def logout(session: requests.Session, auth_realm_url: str):
    """
    Log out of AISR.
    """
    url = f"{auth_realm_url}/protocol/openid-connect/logout?client_id=aisr-app"
    session.request("GET", url, headers={}, data={})
