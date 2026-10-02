"""Shared fixtures: the fake AISR (and fake Infinite Campus) server,
running in-process.

One server per test session, on a free port, in a background thread. A
health poll (not a fixed sleep) decides when it is ready. Faults and the
upload log live on the app and are reset before every test that asks for
`mock_aisr`, so tests can inject failures without leaking them.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import pytest
import requests
import uvicorn
from fastapi import FastAPI
from minnesota_immunization_mock.server import MockFaults, create_mock_app


@dataclass
class MockAisr:
    base_url: str
    app: FastAPI

    @property
    def auth_url(self) -> str:
        return f"{self.base_url}/mock-auth-server"

    @property
    def faults(self) -> MockFaults:
        return self.app.state.faults

    @property
    def received_uploads(self) -> list[str]:
        """School ids whose roster upload succeeded, in order."""
        return self.app.state.received_uploads

    @property
    def ic_url(self) -> str:
        """The fake Infinite Campus served by the same app."""
        return f"{self.base_url}/campus"

    @property
    def ic(self):
        """The fake IC's faults, exports, and device registrations."""
        return self.app.state.ic


@pytest.fixture(scope="session")
def _mock_aisr_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    base_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    app = create_mock_app(base_url=base_url)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()

    deadline = time.monotonic() + 10
    while True:
        try:
            if requests.get(f"{base_url}/health", timeout=1).status_code == 200:
                break
        except requests.ConnectionError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("mock AISR server did not start")
        time.sleep(0.05)

    yield MockAisr(base_url=base_url, app=app)

    server.should_exit = True
    thread.join(timeout=5)
    sock.close()


@pytest.fixture
def mock_aisr(_mock_aisr_server: MockAisr) -> MockAisr:
    """The fake AISR with no faults and an empty upload log."""
    _mock_aisr_server.faults.clear()
    _mock_aisr_server.received_uploads.clear()
    _mock_aisr_server.app.state.uploaded_at.clear()
    _mock_aisr_server.app.state.ic.reset()
    return _mock_aisr_server


@pytest.fixture
def fastapi_server(mock_aisr: MockAisr) -> str:
    """The fake AISR's base URL (the name older tests use)."""
    return mock_aisr.base_url
