"""
Utils used for testing the data pipeline.
"""

import json
import os
import subprocess


def execute_transform_subprocess(input_folder, output_folder, logs_folder):
    """
    Execute the CLI transform command as a subprocess.
    """
    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--input-folder",
            input_folder,
            "--output-folder",
            output_folder,
            "--logs-folder",
            logs_folder,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    return result


def create_test_config(tmp_path, fastapi_server):
    """
    Create a test configuration file that connects to the mock FastAPI server.

    Args:
        tmp_path: Pytest's temporary path fixture
        fastapi_server: URL to the mock FastAPI server

    Returns:
        Path to the configuration file
    """
    auth_base_url = f"{fastapi_server}/mock-auth-server"
    api_base_url = fastapi_server

    config = {
        "api": {"auth_base_url": auth_base_url, "api_base_url": api_base_url},
        "schools": [
            {
                "name": "Friendly Hills",
                "id": "1234",
                "classification": "N",
                "email": "test@example.com",
            }
        ],
    }

    config_path = tmp_path / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    return config_path


def execute_query_subprocess(fastapi_server, tmp_path, username, password=None):
    """
    Execute the CLI query command as a subprocess.

    Args:
        fastapi_server: URL to the mock FastAPI server
        tmp_path: Pytest's temporary path fixture
        username: AISR username
        password: Password for testing. In real usage, password will be prompted
                 interactively or read from AISR_PASSWORD env var if set.

    Returns:
        CompletedProcess object with stdout and stderr
    """
    env = os.environ.copy()

    # For testing purposes, we need to provide the password via environment variable
    if password:
        env["AISR_PASSWORD"] = password

    # Create a test configuration file
    config_file = create_test_config(tmp_path, fastapi_server)

    cmd = [
        "poetry",
        "run",
        "python",
        "data_pipeline",
        "query",
        "--username",
        username,
        "--config",
        str(config_file),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )

    return result
