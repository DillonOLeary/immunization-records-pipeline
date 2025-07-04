"""
Utils used for testing the data pipeline.
"""

# pylint: disable=duplicate-code
import json
import os
import subprocess
from pathlib import Path


def execute_transform_subprocess(config_path=None):
    """
    Execute the CLI transform command as a subprocess.

    Args:
        tmp_path: Pytest's temporary path fixture
        config_path: Optional path to an existing config file. If None,
                    a config will be created using the test_env fixture.

    Returns:
        subprocess.CompletedProcess: Result of the command execution
    """
    # Get the project root directory to run the CLI from
    project_root = Path(__file__).parent.parent

    # Run the transform command with the config file
    result = subprocess.run(
        [
            "uv",
            "run",
            "minnesota-immunization-cli",
            "--config",
            str(config_path),
            "transform",
        ],
        capture_output=True,
        check=False,
        cwd=project_root,  # Run from the CLI project directory
    )

    return result


def create_test_config(config_path, fastapi_server, tmp_path=None):
    """
    Add API server configuration to a test config file and create necessary query files.

    Args:
        config_path: Path to existing configuration file
        fastapi_server: URL to the mock FastAPI server
        tmp_path: Pytest's temporary path fixture. If None,
            uses the directory from config_path.

    Returns:
        Path to the updated configuration file
    """
    if tmp_path is None:
        tmp_path = Path(config_path).parent
    # Read existing config
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    # Add API and school information
    auth_base_url = f"{fastapi_server}/mock-auth-server"
    api_base_url = fastapi_server

    # Create a query file in the bulk_query_folder with a school-specific subfolder
    query_folder = Path(tmp_path) / "bulk_query"
    query_folder.mkdir(exist_ok=True)

    # Create a school-specific folder
    school_folder = query_folder / "Friendly Hills"
    school_folder.mkdir(exist_ok=True)
    query_file_path = school_folder / "query.csv"

    with open(query_file_path, "w", encoding="utf-8") as f:
        f.write("student_id,first_name,last_name,dob\n")
        f.write("12345,John,Doe,2010-01-01\n")
        f.write("67890,Jane,Smith,2011-02-02\n")

    # School configuration
    school_config = {
        "name": "Friendly Hills",
        "id": "1234",
        "classification": "N",
        "email": "test@example.com",
        "bulk_query_file": str(query_file_path),
    }

    config.update(
        {
            "api": {"auth_base_url": auth_base_url, "aisr_api_base_url": api_base_url},
            "schools": [school_config],
        }
    )

    # Write updated config
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    return config_path


def execute_query_subprocess(config_path, username, password=None):
    """
    Execute the CLI bulk-query command as a subprocess.

    Args:
        config_path: Path to configuration file
        username: AISR username
        password: Password for testing. In real usage, password will be prompted
                 interactively or read from AISR_PASSWORD env var if set.

    Returns:
        CompletedProcess object with stdout and stderr
    """
    env = os.environ.copy()

    # Get the project root directory to run the CLI from
    project_root = Path(__file__).parent.parent

    # For testing purposes, we need to provide the password via environment variable
    if password:
        env["AISR_PASSWORD"] = password

    cmd = [
        "uv",
        "run",
        "minnesota-immunization-cli",
        "--config",
        str(config_path),
        "bulk-query",
        "--username",
        username,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        env=env,
        check=False,
        cwd=project_root,  # Run from the CLI project directory
    )

    return result


def execute_download_subprocess(config_path, username, password=None):
    """
    Execute the CLI get-vaccinations command as a subprocess.

    Args:
        config_path: Path to configuration file
        username: AISR username
        password: Password for testing. In real usage, password will be prompted
                 interactively or read from AISR_PASSWORD env var if set.

    Returns:
        CompletedProcess object with stdout and stderr
    """
    env = os.environ.copy()

    # Get the project root directory to run the CLI from
    project_root = Path(__file__).parent.parent

    # For testing purposes, we need to provide the password via environment variable
    if password:
        env["AISR_PASSWORD"] = password

    cmd = [
        "uv",
        "run",
        "minnesota-immunization-cli",
        "--config",
        str(config_path),
        "get-vaccinations",
        "--username",
        username,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        env=env,
        check=False,
        cwd=project_root,  # Run from the CLI project directory
    )

    return result
