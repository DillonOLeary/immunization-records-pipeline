"""The project for secret access must come from config or ADC, never code.

A wrong-project lookup would read another district's secrets, so the
resolution order (the configured GCP_PROJECT, then ADC, then a loud
failure) is worth pinning down.
"""

from types import SimpleNamespace

import pytest

from mn_immunization.adapters.gcs import secrets as secrets_module


class _FakeClient:
    def __init__(self):
        self.requested_name = None

    def access_secret_version(self, request):
        self.requested_name = request["name"]
        return SimpleNamespace(payload=SimpleNamespace(data=b"secret-value"))


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(
        secrets_module.secretmanager,
        "SecretManagerServiceClient",
        lambda: client,
    )
    return client


def test_configured_project_wins_over_adc(monkeypatch, fake_client):
    monkeypatch.setattr(
        secrets_module.google.auth, "default", lambda: (None, "adc-project")
    )

    value = secrets_module.secret_reader("district-a")("miic-username")

    assert value == "secret-value"
    assert fake_client.requested_name == (
        "projects/district-a/secrets/miic-username/versions/latest"
    )


def test_adc_project_used_when_none_configured(monkeypatch, fake_client):
    monkeypatch.setattr(
        secrets_module.google.auth, "default", lambda: (None, "adc-project")
    )

    secrets_module.secret_reader(None)("miic-username")

    assert fake_client.requested_name == (
        "projects/adc-project/secrets/miic-username/versions/latest"
    )


def test_no_project_fails_loudly(monkeypatch, fake_client):
    monkeypatch.setattr(secrets_module.google.auth, "default", lambda: (None, None))

    with pytest.raises(RuntimeError, match="GCP project"):
        secrets_module.secret_reader(None)("miic-username")


def test_nothing_is_resolved_until_a_secret_is_read(monkeypatch, fake_client):
    calls = []
    monkeypatch.setattr(
        secrets_module.google.auth,
        "default",
        lambda: calls.append("adc") or (None, "adc-project"),
    )

    read = secrets_module.secret_reader(None)
    assert calls == []
    read("a")
    read("b")
    assert calls == ["adc"]
