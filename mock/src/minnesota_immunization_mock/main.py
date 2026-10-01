"""`uv run mock-server`: the fake AISR on http://localhost:8080.

Log in with test_user / test_password. Set MOCK_SERVER_URL if the server
is reachable at a different address (it appears in redirect and signed
URLs).
"""

import os

import uvicorn

from .server import create_mock_app


def run():
    """Run the server locally."""
    base_url = os.environ.get("MOCK_SERVER_URL", "http://localhost:8080")
    uvicorn.run(create_mock_app(base_url=base_url), host="127.0.0.1", port=8080)
