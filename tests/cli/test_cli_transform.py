"""
Integration tests for the CLI
"""

import os

from .utils import execute_transform_subprocess


def test_cli_runs_for_all_test_files(tmp_path, test_env):
    # Unpack test environment
    _, _, _, _, config_path = test_env

    result = execute_transform_subprocess(config_path)

    # Check if command executed successfully
    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Check if output files were created
    output_folder = tmp_path / "output"
    assert len(os.listdir(output_folder)) > 0, (
        "No files were created in the output folder"
    )


def test_cli_creates_non_existent_output_folder(test_env):
    # Unpack test environment
    _, output_folder, _, _, config_path = test_env

    # Remove output folder if it exists
    if output_folder.exists():
        for file in output_folder.iterdir():
            file.unlink()
        output_folder.rmdir()

    # Run transform
    result = execute_transform_subprocess(config_path)

    # Check results
    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"
    assert output_folder.exists(), "Output folder was not created."
    assert len(os.listdir(output_folder)) > 0, (
        "No files were created in the output folder."
    )


def test_cli_correct_output_file_contents(test_env):
    # Unpack test environment
    _, output_folder, _, _, config_path = test_env

    # Run transform
    result = execute_transform_subprocess(config_path)

    # Check if command executed successfully
    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Verify output file contents
    output_files = list(output_folder.glob("*.csv"))
    assert len(output_files) == 1, (
        "No output files were created or too many files exist."
    )

    output_file = output_files[0]
    with open(output_file, encoding="utf-8") as f:
        lines = f.readlines()

    expected_lines = [
        "123,456,COVID-19,11/17/2024\n",
        "789,101,Flu,11/16/2024\n",
        "112,131,COVID-19,11/15/2024\n",
    ]

    assert lines == expected_lines, f"Output file contents are incorrect: {lines}"


def test_cli_runs_for_multiple_test_files(test_env):
    # Unpack test environment
    input_folder, output_folder, _, _, config_path = test_env

    # Clear the input folder (remove the default test file)
    for file in input_folder.iterdir():
        file.unlink()

    # Create multiple test CSV files
    test_files = [
        input_folder / "test_file_1.csv",
        input_folder / "test_file_2.csv",
        input_folder / "test_file_3.csv",
    ]

    # Write data to each test file
    for i, test_file in enumerate(test_files, start=1):
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")
            f.write(f"123{i}|456|COVID-19|11/17/2024\n")
            f.write(f"789{i}|101|Flu|11/16/2024\n")
            f.write(f"112{i}|131|COVID-19|11/15/2024\n")

    # Run the transform command, using the existing config file
    result = execute_transform_subprocess(config_path)

    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Verify that multiple files were processed and output files are created
    output_files = sorted(output_folder.glob("*.csv"), key=lambda x: x.name)
    assert len(output_files) == len(test_files), (
        f"Expected {len(test_files)} output files, but found {len(output_files)}."
    )

    # Verify that each output file matches the input file's contents
    for i, output_file in enumerate(output_files, start=1):
        with open(output_file, encoding="utf-8") as f:
            lines = f.readlines()

        # Expected transformed lines
        expected_lines = [
            f"123{i},456,COVID-19,11/17/2024\n",
            f"789{i},101,Flu,11/16/2024\n",
            f"112{i},131,COVID-19,11/15/2024\n",
        ]
        assert lines == expected_lines, f"Output file contents are incorrect: {lines}"


def test_cli_creates_metadata_file_with_correct_fields(test_env):
    # Unpack test environment
    _, output_folder, _, _, config_path = test_env

    # Run transform
    result = execute_transform_subprocess(config_path)

    # Check if command executed successfully
    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Verify metadata file
    metadata_files = list(
        (output_folder / "metadata").glob("*.json")
    )  # Assuming metadata is a JSON file
    assert len(metadata_files) == 1, (
        "Metadata file was not created or too many metadata files found."
    )

    metadata_file = metadata_files[0]
    with open(metadata_file, encoding="utf-8") as f:
        metadata = f.read()

    assert "run_id" in metadata, "metadata file does not contain 'run_id'."
    assert "input_file" in metadata, "metadata file does not contain 'input_file'."
    assert "output_folder" in metadata, (
        "metadata file does not contain 'output_folder'."
    )
    assert "timestamp" in metadata, "metadata file does not contain 'timestamp'."
    assert "version" in metadata, "metadata file does not contain 'version'."
    assert "result_message" in metadata, (
        "metadata file does not contain 'result_message'."
    )


def test_cli_creates_execution_metadata(test_env):
    # Unpack test environment
    _, output_folder, _, _, config_path = test_env

    # Run transform
    result = execute_transform_subprocess(config_path)

    # Check if command executed successfully
    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Verify execution metadata file was created
    metadata_folder = output_folder / "metadata"

    # Check if metadata folder exists
    assert metadata_folder.exists(), "Metadata folder was not created"

    # Look for files that start with execution_metadata
    execution_metadata_files = list(metadata_folder.glob("execution_metadata*.json"))
    assert len(execution_metadata_files) > 0, "No execution metadata files were created"
