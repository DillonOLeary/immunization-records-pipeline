"""
Utils used for testing the data pipeline.
"""

import json
import os
import subprocess


def execute_transform_subprocess(tmp_path, config_path=None):
    """
    Execute the CLI transform command as a subprocess.

    Args:
        tmp_path: Pytest's temporary path fixture
        config_path: Optional path to an existing config file. If None,
                    a config will be created using the test_env fixture.

    Returns:
        subprocess.CompletedProcess: Result of the command execution
    """
    # Run the transform command with the config file
    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--config",
            str(config_path),
            "transform",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    return result


def create_test_config(tmp_path, config_path, fastapi_server):
    """
    Add API server configuration to a test config file.

    Args:
        tmp_path: Pytest's temporary path fixture
        config_path: Path to existing configuration file
        fastapi_server: URL to the mock FastAPI server

    Returns:
        Path to the updated configuration file
    """
    # Read existing config
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Add API and school information
    auth_base_url = f"{fastapi_server}/mock-auth-server"
    api_base_url = fastapi_server

    config.update(
        {
            "api": {"auth_base_url": auth_base_url, "aisr_api_base_url": api_base_url},
            "schools": [
                {
                    "name": "Friendly Hills",
                    "id": "1234",
                    "classification": "N",
                    "email": "test@example.com",
                }
            ],
        }
    )

    # Write updated config
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    return config_path


def execute_query_subprocess(fastapi_server, config_path, username, password=None):
    """
    Execute the CLI bulk-query command as a subprocess.

    Args:
        fastapi_server: URL to the mock FastAPI server
        config_path: Path to configuration file
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

    cmd = [
        "poetry",
        "run",
        "python",
        "data_pipeline",
        "--config",
        str(config_path),
        "bulk-query",
        "--username",
        username,
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )

    return result
