"""
Query MIIC for school immunization data
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Tuple
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _get_session_and_tab(s: requests.Session, auth_realm_url: str) -> Tuple[str, str]:
    """
    The session and tab are needed to authenticate with AISR.
    """
    state = uuid.uuid4()
    nonce = uuid.uuid4()

    # pylint: disable-next=line-too-long
    url = f"{auth_realm_url}/protocol/openid-connect/auth?client_id=aisr-app&redirect_uri=https%3A%2F%2Faisr.web.health.state.mn.us%2Fhome&state={state}&response_mode=fragment&response_type=code&scope=openid&nonce={nonce}"

    response = s.request("GET", url, headers={}, data={})
    soup = BeautifulSoup(response.content, "html.parser")
    form_element = soup.find("form", id="kc-form-login")
    action_url = form_element.get("action") if form_element else None
    parsed_url = urlparse(action_url)
    query_dict = parse_qs(parsed_url.query)

    return query_dict["session_code"][0], query_dict["tab_id"][0]


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
    url = f"{auth_realm_url}/login-actions/authenticate?session_code={session_code}&execution={uuid.uuid4()}&client_id=aisr-app&tab_id={tab_id}"

    payload = f"password={quote(password)}&username={username}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = session.request("POST", url, headers=headers, data=payload)

    if response.status_code == 200:
        logger.info("Logged in successfully")
        return AISRResponse(is_successful=True, message="Logged in successfully")

    logger.error("Login failed")
    return AISRResponse(is_successful=False, message="Failed to log in")
