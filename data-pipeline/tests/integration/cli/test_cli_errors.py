"""
Integration tests for the check-errors command.
"""

import subprocess
from datetime import datetime


def test_check_errors_command(test_env):
    """
    Test that the check-errors command runs successfully.
    """
    # Unpack test environment
    _, _, logs_folder, _, config_path = test_env

    # Create a test log file with current timestamps to ensure they're within any time range
    log_file = logs_folder / "test_error.log"
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(
            f"{timestamp},123 - ERROR - test_module - test_function:42 - Test error message\n"
        )
        f.write(
            f"{timestamp},456 - ERROR - test_module - another_function:123 - Another test error\n"
        )

    # Run the check-errors command
    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--config",
            str(config_path),
            "check-errors",
            "--scope",
            "all",  # Use "all" scope to ensure we find all errors regardless of date
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    # Check if command executed successfully
    assert (
        result.returncode == 0
    ), f"Command failed with error: {result.stderr.decode()}"

    # Check output for expected content
    output = result.stdout.decode()
    assert "Found 2 errors in logs" in output
    assert "test_module" in output
    assert "Test error message" in output
    assert "Another test error" in output


def test_check_errors_with_scope(test_env):
    """
    Test that the check-errors command works with scope=all option.

    This test focuses on verifying that the CLI correctly accepts and processes
    the scope parameter, rather than testing the actual date filtering logic
    (which is covered in unit tests).
    """
    # Unpack test environment
    _, _, logs_folder, _, config_path = test_env

    # Create a test log file with current timestamps
    log_file = logs_folder / "test_error.log"
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    # Create three different error messages to test for in the output
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"{timestamp},123 - ERROR - module1 - func:42 - First error message\n")
        f.write(f"{timestamp},456 - ERROR - module2 - func:43 - Second error message\n")
        f.write(f"{timestamp},789 - ERROR - module3 - func:44 - Third error message\n")

    # Run with scope=all (should find all errors)
    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--config",
            str(config_path),
            "check-errors",
            "--scope",
            "all",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    # Check output - should have found all errors
    output = result.stdout.decode()
    assert (
        result.returncode == 0
    ), f"Command failed with error: {result.stderr.decode()}"
    assert "Found 3 errors in logs" in output
    assert "First error message" in output
    assert "Second error message" in output
    assert "Third error message" in output

    # Also verify that different modules are reported correctly
    assert "module1" in output
    assert "module2" in output
    assert "module3" in output
