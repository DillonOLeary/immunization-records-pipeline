"""The project for secret access must come from config or ADC, never code.

A wrong-project lookup would read another district's secrets, so the
resolution order (GCP_PROJECT, then ADC, then a loud failure) is worth
pinning down.
"""

from types import SimpleNamespace

import pytest

from mn_immunization.gcp import secrets as secrets_module


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


def test_env_var_project_wins_over_adc(monkeypatch, fake_client):
    monkeypatch.setenv("GCP_PROJECT", "district-a")
    monkeypatch.setattr(
        secrets_module.google.auth, "default", lambda: (None, "adc-project")
    )

    value = secrets_module.get_secret("aisr-username")

    assert value == "secret-value"
    assert fake_client.requested_name == (
        "projects/district-a/secrets/aisr-username/versions/latest"
    )


def test_adc_project_used_when_env_unset(monkeypatch, fake_client):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.setattr(
        secrets_module.google.auth, "default", lambda: (None, "adc-project")
    )

    secrets_module.get_secret("aisr-username")

    assert fake_client.requested_name == (
        "projects/adc-project/secrets/aisr-username/versions/latest"
    )


def test_no_project_fails_loudly(monkeypatch, fake_client):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.setattr(secrets_module.google.auth, "default", lambda: (None, None))

    with pytest.raises(RuntimeError, match="GCP project"):
        secrets_module.get_secret("aisr-username")
