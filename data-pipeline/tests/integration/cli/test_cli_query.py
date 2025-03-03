"""
Integration tests for the CLI query command.
"""

import os

from tests.test_utils import create_test_config, execute_query_subprocess

# Constants for test
USERNAME = "test_user"
PASSWORD = "test_password"


def test_cli_query_executes_successfully(fastapi_server, test_env):
    """
    Test that the CLI query command runs successfully.
    """
    # Unpack test environment
    _, _, _, _, config_path = test_env

    # Add API configuration
    config_path = create_test_config(config_path, fastapi_server)

    result = execute_query_subprocess(
        config_path=config_path,
        username=USERNAME,
        password=PASSWORD,
    )

    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"
    assert "Processing request for Friendly Hills" in result.stdout.decode()


def test_cli_query_with_env_password(fastapi_server, test_env):
    """
    Test that the CLI query command works with password provided via environment variable.
    """
    # Unpack test environment
    _, _, _, _, config_path = test_env

    # Add API configuration
    config_path = create_test_config(config_path, fastapi_server)

    # Set up environment variable instead of passing password directly
    os.environ["AISR_PASSWORD"] = PASSWORD

    try:
        result = execute_query_subprocess(
            config_path=config_path,
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


def test_cli_query_authentication_failure(fastapi_server, test_env):
    """
    Test that the CLI shows appropriate error message on authentication failure.
    """
    # Unpack test environment
    _, _, _, _, config_path = test_env

    # Add API configuration
    config_path = create_test_config(config_path, fastapi_server)

    result = execute_query_subprocess(
        config_path=config_path,
        username="wrong_user",
        password="wrong_password",
    )

    # Instead of checking return code, verify that authentication error is in output
    output = result.stdout.decode() + result.stderr.decode()
    assert (
        "Login failed" in output
        or "Invalid credentials" in output
        or "Authentication failed" in output
    ), "Should show authentication failure message"
