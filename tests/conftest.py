"""
Pytest utils
"""

import multiprocessing
import time
from multiprocessing import Process

import pytest
import uvicorn

from tests.mock_server import create_mock_app

# Set the start method to 'fork' to avoid pickling issues on macOS
try:
    multiprocessing.set_start_method("fork")
except RuntimeError:
    # Method was already set, ignore the error
    pass


def run_server(app):
    """Run the FastAPI server."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


@pytest.fixture(scope="session")
def fastapi_server():
    """
    Spins up a FastAPI server for testing.
    """
    app = create_mock_app()
    process = Process(target=run_server, args=(app,), daemon=True)
    process.start()

    # Wait for the server to start up
    time.sleep(1)

    yield "http://127.0.0.1:8000"

    process.terminate()
    process.join()
