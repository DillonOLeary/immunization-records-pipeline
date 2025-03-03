"""
Integration tests for the CLI query command.
"""

import os
import subprocess

from tests.test_utils import execute_query_subprocess

# Constants for test
USERNAME = "test_user"
PASSWORD = "test_password"


def test_cli_query_executes_successfully(fastapi_server, tmp_path):
    """
    Test that the CLI query command runs successfully.
    """
    result = execute_query_subprocess(
        fastapi_server=fastapi_server,
        tmp_path=tmp_path,
        username=USERNAME,
        password=PASSWORD,
    )

    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"
    assert "Processing request for Friendly Hills" in result.stdout.decode()


def test_cli_query_with_env_password(fastapi_server, tmp_path):
    """
    Test that the CLI query command works with password provided via environment variable.
    """
    # Set up environment variable instead of passing password directly
    os.environ["AISR_PASSWORD"] = PASSWORD

    try:
        result = execute_query_subprocess(
            fastapi_server=fastapi_server,
            tmp_path=tmp_path,
            username=USERNAME,
            # No password passed explicitly
        )

        assert (
            result.returncode == 0
        ), f"CLI failed with error: {result.stderr.decode()}"
        assert "Processing request for Friendly Hills" in result.stdout.decode()
    finally:
        # Clean up environment variable
        del os.environ["AISR_PASSWORD"]


def test_cli_query_authentication_failure(fastapi_server, tmp_path):
    """
    Test that the CLI shows appropriate error message on authentication failure.
    """
    result = execute_query_subprocess(
        fastapi_server=fastapi_server,
        tmp_path=tmp_path,
        username="wrong_user",
        password="wrong_password",
    )

    assert result.returncode != 0, "CLI should have failed with wrong credentials"
    assert "Authentication failed" in result.stderr.decode()
