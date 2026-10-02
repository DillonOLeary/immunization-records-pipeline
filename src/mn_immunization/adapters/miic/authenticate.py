"""
Handle authentication with AISR.
"""

import logging
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from mn_immunization.workflow.ports import RegistryError, RegistryLoginError

logger = logging.getLogger(__name__)

# (connect, read) seconds for every Keycloak call. Without a timeout a
# hung login would hold the job until its 22-hour task timeout.
AUTH_TIMEOUT = (10, 60)


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


class AuthenticationError(RegistryLoginError):
    """AISR refused the credentials: a 401, or no session afterwards (an
    expired password lands on Keycloak's "update password" page)."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return self.message


class LoginUnavailableError(RegistryError):
    """AISR's login answered with a server error: transient, unlike a
    refusal, so a waiting period keeps waiting."""


@dataclass
class AISRAuthResponse:
    """
    Dataclass to hold successful authentication details.
    """

    access_token: str


def _get_login_action_url(session: requests.Session, base_url: str) -> str:
    """Scrape the login form's action URL from the live auth page.

    Keycloak embeds every flow parameter (session_code, execution, tab_id)
    in that URL; POSTing back to it verbatim is what a browser does, so a
    MIIC change to the flow's parameters cannot break the login.
    """
    state = uuid.uuid4()
    nonce = uuid.uuid4()

    url = f"{base_url}/auth/realms/idepc-aisr-realm/protocol/openid-connect/auth?client_id=aisr-app&redirect_uri=https%3A%2F%2Faisr.web.health.state.mn.us%2Fhome&state={state}&response_mode=fragment&response_type=code&scope=openid&nonce={nonce}"  # noqa: E501

    response = session.request("GET", url, timeout=AUTH_TIMEOUT)
    soup = BeautifulSoup(response.content, "html.parser")
    form_element = soup.find("form", id="kc-form-login")

    if isinstance(form_element, Tag):
        action_url = form_element.get("action")
        if isinstance(action_url, str) and action_url:
            # Relative actions resolve against the page they came from.
            return urljoin(response.url, action_url)
        raise ValueError("The login form has no usable action URL.")
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
        "POST",
        url,
        headers=headers,
        data=payload,
        allow_redirects=False,
        timeout=AUTH_TIMEOUT,
    )

    if response.status_code != 200:
        # Status only: the body is not ours to put in a log line.
        raise TokenRequestError(response.status_code)
    return response.json().get("access_token")


def login(
    session: requests.Session, base_url: str, username: str, password: str
) -> AISRAuthResponse:
    """
    Login with AISR.

    Returns:
        AISRAuthResponse with access token on success

    Raises:
        AuthenticationError: If login fails for any reason
    """
    logger.info("Logging into MIIC")
    action_url = _get_login_action_url(session, base_url)

    # A dict body is form-encoded by requests, so both fields are escaped
    # (the username used to go in raw, breaking on "+" or "&").
    response = session.request(
        "POST",
        action_url,
        data={"username": username, "password": password},
        allow_redirects=False,
        timeout=AUTH_TIMEOUT,
    )

    if response.status_code == 302 and "KEYCLOAK_IDENTITY" in session.cookies:
        logger.info("Logged in successfully")
        access_token = _get_access_token_using_response_code(
            session, base_url, _get_code_from_response(response)
        )
        return AISRAuthResponse(access_token=access_token)

    if response.status_code >= 500:
        raise LoginUnavailableError(
            f"HTTP {response.status_code} at login", response.status_code
        )

    # Handle authentication failures
    if response.status_code == 401:
        # Generic error message without revealing authentication details
        error_msg = "Login failed: Invalid credentials"
        logger.error(error_msg)
        raise AuthenticationError(error_msg)

    error_msg = "Login failed or KEYCLOAK_IDENTITY cookie is missing"
    logger.error(error_msg)
    raise AuthenticationError(error_msg)


def logout(session: requests.Session, base_url: str) -> None:
    """
    Log out of AISR.
    """
    url = f"{base_url}/auth/realms/idepc-aisr-realm/protocol/openid-connect/logout?client_id=aisr-app"  # noqa: E501
    session.request("GET", url, timeout=AUTH_TIMEOUT)
    logger.info("Logged out successfully")
