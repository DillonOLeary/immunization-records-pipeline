"""
Pytest utils
"""

import json
import multiprocessing
import shutil
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


@pytest.fixture(name="test_env")
def setup_test_environment(tmp_path):
    """
    Create a test environment with input, output, and logs folders,
    plus a test input file and config file.

    Args:
        tmp_path: Pytest's temporary path fixture

    Returns:
        tuple: (input_folder, output_folder, logs_folder, config_file)
    """
    # Create necessary folders
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    logs_folder = tmp_path / "logs"
    bulk_query_folder = tmp_path / "bulk_query"

    for folder in [input_folder, output_folder, logs_folder, bulk_query_folder]:
        folder.mkdir(exist_ok=True)

    # Create a sample input file
    test_file = input_folder / "test_file.csv"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")
        f.write("123|456|COVID-19|11/17/2024\n")
        f.write("789|101|Flu|11/16/2024\n")
        f.write("112|131|COVID-19|11/15/2024\n")

    # Create a config file for the transform command
    config_path = tmp_path / "config.json"

    # Create config with paths
    config = {
        "paths": {
            "input_folder": str(input_folder),
            "output_folder": str(output_folder),
            "logs_folder": str(logs_folder),
        }
    }

    # Write config to file
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    yield input_folder, output_folder, logs_folder, bulk_query_folder, config_path

    # Clean up after test - much simpler with shutil.rmtree
    # First, delete all files in each directory
    for folder in [input_folder, output_folder, logs_folder, bulk_query_folder]:
        # Make directory empty but preserve the directory itself
        for item in folder.glob("*"):
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)


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
