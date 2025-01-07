"""
Pytest utils
"""

import time
from multiprocessing import Process
from pathlib import Path

import pytest
import uvicorn
from data_pipeline.pipeline_factory import use_web_driver
from fastapi import FastAPI
from fastapi.responses import HTMLResponse


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


@pytest.fixture
def selenium_driver():
    """
    Sets up the driver for the tests.
    """
    target_url = "http://127.0.0.1:8000"

    with use_web_driver(target_url) as driver:
        yield driver
