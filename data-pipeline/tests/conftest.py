"""
Pytest utils
"""

import time
from multiprocessing import Process
from pathlib import Path

import pytest
import uvicorn

from tests.mock_server import create_mock_app


@pytest.fixture(name="folders")
def input_output_logs_folders():
    """
    Allows tests to use input and output folders
    """
    input_folder = Path(".") / "tests" / "test_input"
    output_folder = Path(".") / "tests" / "test_output"
    logs_folder = Path(".") / "tests" / "test_logs"
    metadata_folder = output_folder / "metadata"

    # Create directories
    for folder in [input_folder, output_folder, logs_folder]:
        folder.mkdir(parents=True, exist_ok=True)

    # Yield the folders for test usage
    yield input_folder, output_folder, logs_folder

    # Cleanup after the test
    for folder in [metadata_folder, input_folder, output_folder, logs_folder]:
        if folder.exists():
            for file in folder.iterdir():
                file.unlink()
            folder.rmdir()


@pytest.fixture(scope="session")
def fastapi_server():
    """
    Spins up a FastAPI server for testing.
    """
    app = create_mock_app()

    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8000)

    process = Process(target=run_server, daemon=True)
    process.start()

    # Wait for the server to start up
    time.sleep(1)

    yield "http://127.0.0.1:8000"

    process.terminate()
    process.join()
