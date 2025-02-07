"""
Handle authentication with AISR.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


class CodeNotFoundError(Exception):
    """Custom exception for when the authorization code is not found in the response."""

    def __init__(self, message=None):
        self.message = (
            message or "Authorization code not found in response Location header."
        )

    def __str__(self):
        return self.message


class TokenRequestError(Exception):
    """Custom exception for errors during token request."""

    def __init__(self, status_code, message=None):
        self.status_code = status_code
        self.message = (
            message or f"Token request failed with status code: {status_code}"
        )

    def __str__(self):
        return self.message


@dataclass
class AISRAuthResponse:
    """
    Dataclass to hold auth related response from interactions with AISR.
    """

    # FIXME just get rid of this and through an error if auth fails

    is_successful: bool
    message: str
    access_token: Optional[str] = None


def _get_session_code_and_tab_id(
    session: requests.Session, base_url: str
) -> Tuple[str, str]:
    """
    The session and tab are needed to authenticate with AISR.
    """
    state = uuid.uuid4()
    nonce = uuid.uuid4()

    # pylint: disable-next=line-too-long
    url = f"{base_url}/auth/realms/idepc-aisr-realm/protocol/openid-connect/auth?client_id=aisr-app&redirect_uri=https%3A%2F%2Faisr.web.health.state.mn.us%2Fhome&state={state}&response_mode=fragment&response_type=code&scope=openid&nonce={nonce}"

    response = session.request("GET", url, headers={}, data={})
    soup = BeautifulSoup(response.content, "html.parser")
    form_element = soup.find("form", id="kc-form-login")

    # the session code and tab id are found in the action URL of the form
    if isinstance(form_element, Tag):
        action_url = form_element.get("action")
        if isinstance(action_url, str):
            parsed_url = urlparse(action_url)
            query_dict = parse_qs(parsed_url.query)
            return query_dict["session_code"][0], query_dict["tab_id"][0]
        raise ValueError("The action URL is not a valid string.")
    raise ValueError("Login form not found or is not a valid HTML form element.")


def _get_code_from_response(response: requests.Response) -> str:
    """
    Get the code from the response.
    """
    location = response.headers.get("Location")
    if location:
        parsed_url = urlparse(location)
        fragment = parsed_url.fragment
        fragment_dict = parse_qs(fragment)
        code_list = fragment_dict.get("code")
        if code_list:
            return code_list[0]
        raise CodeNotFoundError("Code not found in response fragment.")
    raise CodeNotFoundError("Code not found in response Location header.")


def _get_access_token_using_response_code(
    session: requests.Session, base_url: str, code: str
) -> str:
    """
    Get the access token from the response.
    """
    url = f"{base_url}/auth/realms/idepc-aisr-realm/protocol/openid-connect/token"

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://aisr.web.health.state.mn.us/home",
        "client_id": "aisr-app",
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    response = session.request(
        "POST", url, headers=headers, data=payload, allow_redirects=False
    )

    if response.status_code != 200:
        raise TokenRequestError(response.status_code, response.text)
    return response.json().get("access_token")


def login(
    session: requests.Session, base_url: str, username: str, password: str
) -> AISRAuthResponse:
    """
    Login with AISR.
    """
    logger.info("Logging into MIIC with username %s", username)
    session_code, tab_id = _get_session_code_and_tab_id(session, base_url)

    # pylint: disable-next=line-too-long
    url = f"{base_url}/auth/realms/idepc-aisr-realm/login-actions/authenticate?session_code={session_code}&execution=084dee30-925f-4a8f-829d-7a372e38d0de&client_id=aisr-app&tab_id={tab_id}"

    payload = f"password={quote(password)}&username={username}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = session.request(
        "POST", url, headers=headers, data=payload, allow_redirects=False
    )

    if response.status_code == 302 and "KEYCLOAK_IDENTITY" in session.cookies:
        logger.info("Logged in successfully")
        return AISRAuthResponse(
            is_successful=True,
            message="Logged in successfully",
            access_token=_get_access_token_using_response_code(
                session, base_url, _get_code_from_response(response)
            ),
        )

    logger.error("Login failed or KEYCLOAK_IDENTITY cookie is missing")
    return AISRAuthResponse(
        is_successful=False,
        message="Login failed or KEYCLOAK_IDENTITY cookie is missing",
    )


def logout(session: requests.Session, base_url: str) -> AISRAuthResponse:
    """
    Log out of AISR.
    """
    # pylint: disable-next=line-too-long
    url = f"{base_url}/auth/realms/idepc-aisr-realm/protocol/openid-connect/logout?client_id=aisr-app"
    session.request("GET", url, headers={}, data={})
    return AISRAuthResponse(
        is_successful=True,
        message="Logged out successfully",
    )
