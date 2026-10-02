"""AISR adapter resilience, against a scripted fake session.

What these pin down: retries key off the HTTP status (never message text)
and apply only to calls with no side effects; the roster upload is never
retried; error messages never carry a response body; every Keycloak call
has a timeout; login form-encodes both fields; and a failed logout never
masks the error that actually ended the session.
"""

import json

import pytest
from tenacity import wait_none

from mn_immunization.adapters.miic import authenticate
from mn_immunization.adapters.miic.actions import (
    AISRActionFailedError,
    DistrictInfo,
    S3UploadHeaders,
    _get_put_url,
    _put_file_to_s3,
    list_result_entries,
    staged_results,
)
from mn_immunization.adapters.miic.client import aisr_session
from mn_immunization.workflow.ports import RegistryError, RegistryLoginError

DISTRICT = DistrictInfo(iddis="0197", s3_upload_host="mock-s3-host")

CANARY_BODY = "Zelda Canaryfield 1999-12-31"


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None, url=""):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.url = url
        text = body if isinstance(body, str) else json.dumps(body)
        self.text = text
        self.content = text.encode("utf-8")

    def json(self):
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body


class ScriptedSession:
    """Returns scripted responses in order (the last repeats) and records
    every call's keyword arguments."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        outcome = (
            self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    def request(self, method, url, **kwargs):
        return self._next(method, url, kwargs)


def no_wait(fn):
    return fn.retry_with(wait=wait_none())


# --- retries key off the status, and only for side-effect-free calls ---


def test_signing_retries_a_503_then_succeeds():
    session = ScriptedSession(
        FakeResponse(503, CANARY_BODY), FakeResponse(200, {"url": "https://s3/put"})
    )
    url = no_wait(_get_put_url)(session, "https://api", "token", "f.csv", "2542")
    assert url == "https://s3/put"
    assert len(session.calls) == 2


def test_signing_does_not_retry_a_404():
    session = ScriptedSession(FakeResponse(404, CANARY_BODY))
    with pytest.raises(AISRActionFailedError) as caught:
        no_wait(_get_put_url)(session, "https://api", "token", "f.csv", "2542")
    assert caught.value.status_code == 404
    assert len(session.calls) == 1


def test_a_body_mentioning_502_is_not_a_transient_status():
    # The old predicate matched "502" anywhere in the message, which
    # included the response body.
    session = ScriptedSession(FakeResponse(400, "error code 502 in body"))
    with pytest.raises(AISRActionFailedError):
        no_wait(list_result_entries)(session, "https://api", "token", "2542")
    assert len(session.calls) == 1


def test_signing_rejects_a_response_without_a_url():
    session = ScriptedSession(FakeResponse(200, {"nope": True}))
    with pytest.raises(AISRActionFailedError):
        no_wait(_get_put_url)(session, "https://api", "token", "f.csv", "2542")


def test_signing_rejects_unreadable_json():
    session = ScriptedSession(FakeResponse(200, "<html>maintenance</html>"))
    with pytest.raises(AISRActionFailedError):
        no_wait(_get_put_url)(session, "https://api", "token", "f.csv", "2542")


def test_roster_upload_is_never_retried(tmp_path):
    # The upload is what makes MIIC email every nurse; an unknown outcome
    # must fail loudly rather than risk a second email.
    roster = tmp_path / "roster.csv"
    roster.write_text("id\n1\n", encoding="utf-8")
    session = ScriptedSession(FakeResponse(503, CANARY_BODY))
    with pytest.raises(AISRActionFailedError) as caught:
        _put_file_to_s3(
            session,
            "https://s3/put",
            S3UploadHeaders("N", "2542", "n@x", "0197", "host"),
            str(roster),
        )
    assert caught.value.status_code == 503
    assert len(session.calls) == 1


def test_listing_retries_through_transient_statuses():
    session = ScriptedSession(
        FakeResponse(502, ""), FakeResponse(504, ""), FakeResponse(200, [{"a": 1}])
    )
    entries = no_wait(list_result_entries)(session, "https://api", "token", "2542")
    assert entries == [{"a": 1}]
    assert len(session.calls) == 3


# --- error messages never carry a response body ---


@pytest.mark.parametrize("status", [400, 500, 503])
def test_error_messages_never_include_the_body(status):
    session = ScriptedSession(FakeResponse(status, CANARY_BODY))
    with pytest.raises(AISRActionFailedError) as caught:
        no_wait(list_result_entries)(session, "https://api", "token", "2542")
    assert "Zelda" not in str(caught.value)
    assert str(status) in str(caught.value)


def test_token_request_error_drops_the_body():
    session = ScriptedSession(FakeResponse(400, CANARY_BODY))
    with pytest.raises(authenticate.TokenRequestError) as caught:
        authenticate._get_access_token_using_response_code(session, "https://auth", "c")
    assert "Zelda" not in str(caught.value)


# --- staging observation ---


def test_staged_results_reports_availability_and_listing_shape():
    entries = [
        {"uploadDateTime": 1_740_764_967_763, "fullVaccineFileUrl": "https://old"},
        {"uploadDateTime": 1_759_300_000_000, "fullVaccineFileUrl": "https://new"},
    ]
    results = staged_results(
        ScriptedSession(FakeResponse(200, entries)), "https://api", "token", "2542"
    )
    assert results.available
    assert results.entries == 2
    assert results.newest_upload_at is not None
    assert results.newest_upload_at.year == 2025


def test_latest_entry_without_a_results_file_is_not_staged():
    entries = [{"uploadDateTime": 1, "fullVaccineFileUrl": None}]
    results = staged_results(
        ScriptedSession(FakeResponse(200, entries)), "https://api", "token", "2542"
    )
    assert not results.available


# --- Keycloak: timeouts and form encoding ---


LOGIN_PAGE = '<form id="kc-form-login" action="https://auth/login-actions/x"></form>'


def test_every_keycloak_call_has_a_timeout_and_login_encodes_both_fields():
    session = ScriptedSession(
        FakeResponse(200, LOGIN_PAGE, url="https://auth/page"),
        FakeResponse(302, "", headers={"Location": "https://app#code=abc"}),
        FakeResponse(200, {"access_token": "tok"}),
        FakeResponse(200, ""),
    )
    session.cookies = {"KEYCLOAK_IDENTITY": "x"}

    auth = authenticate.login(session, "https://auth", "user+name&x", "p@ss")
    authenticate.logout(session, "https://auth")

    assert auth.access_token == "tok"
    assert all(kwargs.get("timeout") for _, _, kwargs in session.calls)
    login_post = session.calls[1]
    # A dict body: requests form-encodes it, so "+" and "&" survive.
    assert login_post[2]["data"] == {"username": "user+name&x", "password": "p@ss"}


@pytest.mark.parametrize(
    ("status", "page", "refused"),
    [
        (401, "", True),  # wrong credentials
        (200, "<form>Update password</form>", True),  # expired password
        (503, "", False),  # Keycloak down: wait it out
    ],
)
def test_a_refused_login_is_told_apart_from_an_unavailable_one(status, page, refused):
    session = ScriptedSession(
        FakeResponse(200, LOGIN_PAGE, url="https://auth/page"),
        FakeResponse(status, page),
    )
    session.cookies = {}

    with pytest.raises(RegistryError) as caught:
        authenticate.login(session, "https://auth", "user", "expired")

    assert isinstance(caught.value, RegistryLoginError) is refused


# --- logout never masks the real error ---


def test_failed_logout_does_not_mask_the_error_that_ended_the_session(monkeypatch):
    monkeypatch.setattr(
        "mn_immunization.adapters.miic.client.login",
        lambda *a, **k: authenticate.AISRAuthResponse(access_token="tok"),
    )

    def broken_logout(*_args, **_kwargs):
        raise ConnectionError("logout failed")

    monkeypatch.setattr("mn_immunization.adapters.miic.client.logout", broken_logout)

    with pytest.raises(KeyError):
        with aisr_session("https://auth", "https://api", "u", "p", DISTRICT, {}):
            raise KeyError("the real failure")


def test_failed_logout_alone_is_swallowed(monkeypatch, caplog):
    monkeypatch.setattr(
        "mn_immunization.adapters.miic.client.login",
        lambda *a, **k: authenticate.AISRAuthResponse(access_token="tok"),
    )

    def broken_logout(*_args, **_kwargs):
        raise ConnectionError("logout failed")

    monkeypatch.setattr("mn_immunization.adapters.miic.client.logout", broken_logout)

    with aisr_session("https://auth", "https://api", "u", "p", DISTRICT, {}):
        pass

    assert "AISR logout failed (ConnectionError)" in caplog.text
