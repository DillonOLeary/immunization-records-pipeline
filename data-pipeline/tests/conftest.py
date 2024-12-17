"""
Pytest utils
"""

import time
from multiprocessing import Process
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse


@pytest.fixture(name="folders")
def input_output_log_folders():
    """
    Allows tests to use input, output, and log folders
    """
    input_folder = Path(".") / "tests" / "test_input"
    output_folder = Path(".") / "tests" / "test_output"
    log_folder = Path(".") / "tests" / "test_log"

    # Create directories
    for folder in [input_folder, output_folder, log_folder]:
        folder.mkdir(parents=True, exist_ok=True)

    # Yield the folders for test usage
    yield input_folder, output_folder, log_folder

    # Cleanup after the test
    for folder in [input_folder, output_folder, log_folder]:
        if folder.exists():
            for file in folder.iterdir():
                file.unlink()
            folder.rmdir()


@pytest.fixture(scope="session")
def fastapi_server():
    """
    Spins up a FastAPI server for integration tests.
    Serves a boilerplate HTML page with a <h1> tag: 'Hello Minnesota!'
    """
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Test Page</title>
        </head>
        <body>
            <h1>Hello Minnesota!</h1>
        </body>
        </html>
        """

    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8000)

    process = Process(target=run_server, daemon=True)
    process.start()

    # Wait for the server to start up
    time.sleep(1)

    yield "http://127.0.0.1:8000"

    process.terminate()
    process.join()
