"""
Integration tests for the CLI
"""

import os
import subprocess

# pylint: disable=missing-function-docstring


def test_cli_runs_for_all_test_files(folders):
    input_folder, output_folder, log_folder = folders

    test_file = os.path.join(input_folder, "test_file.csv")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")
        f.write("123|456|COVID-19|11/17/2024\n")
        f.write("789|101|Flu|11/16/2024\n")
        f.write("112|131|COVID-19|11/15/2024\n")

    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--input_folder",
            input_folder,
            "--output_folder",
            output_folder,
            "--log_folder",
            log_folder,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"
    assert (
        len(os.listdir(output_folder)) > 0
    ), "No files were created in the output folder"


def test_cli_creates_non_existent_output_folder(folders):
    input_folder, output_folder, log_folder = folders

    test_file = os.path.join(input_folder, "test_file.csv")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")
        f.write("123|456|COVID-19|11/17/2024\n")
        f.write("789|101|Flu|11/16/2024\n")
        f.write("112|131|COVID-19|11/15/2024\n")

    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--input_folder",
            input_folder,
            "--output_folder",
            output_folder,
            "--log_folder",
            log_folder,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"
    assert output_folder.exists(), "Output folder was not created."
    assert (
        len(os.listdir(output_folder)) > 0
    ), "No files were created in the output folder."


def test_cli_correct_output_file_contents(folders):
    input_folder, output_folder, log_folder = folders

    test_file = os.path.join(input_folder, "test_file.csv")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")
        f.write("123|456|COVID-19|11/17/2024\n")
        f.write("789|101|Flu|11/16/2024\n")
        f.write("112|131|COVID-19|11/15/2024\n")

    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--input_folder",
            input_folder,
            "--output_folder",
            output_folder,
            "--log_folder",
            log_folder,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    output_files = list(output_folder.glob("*.csv"))
    assert (
        len(output_files) == 1
    ), "No output files were created or too many files exist."

    output_file = output_files[0]
    with open(output_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    expected_lines = [
        "123,456,COVID-19,11/17/2024\n",
        "789,101,Flu,11/16/2024\n",
        "112,131,COVID-19,11/15/2024\n",
    ]

    assert lines == expected_lines, f"Output file contents are incorrect: {lines}"


def test_cli_runs_for_multiple_test_files(folders):
    input_folder, output_folder, log_folder = folders

    # Create multiple test CSV files
    test_files = [
        os.path.join(input_folder, "test_file_1.csv"),
        os.path.join(input_folder, "test_file_2.csv"),
        os.path.join(input_folder, "test_file_3.csv"),
    ]

    # Write data to each test file
    for i, test_file in enumerate(test_files, start=1):
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")
            f.write(f"123{i}|456|COVID-19|11/17/2024\n")
            f.write(f"789{i}|101|Flu|11/16/2024\n")
            f.write(f"112{i}|131|COVID-19|11/15/2024\n")

    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--input_folder",
            input_folder,
            "--output_folder",
            output_folder,
            "--log_folder",
            log_folder,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Verify that multiple files were processed and output files are created
    output_files = sorted(list(output_folder.glob("*.csv")), key=lambda x: x.name)
    assert len(output_files) == len(
        test_files
    ), f"Expected {len(test_files)} output files, but found {len(output_files)}."

    # Verify that each output file matches the input file's contents
    for i, output_file in enumerate(output_files, start=1):
        with open(output_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Expected transformed lines
        expected_lines = [
            f"123{i},456,COVID-19,11/17/2024\n",
            f"789{i},101,Flu,11/16/2024\n",
            f"112{i},131,COVID-19,11/15/2024\n",
        ]
        assert lines == expected_lines, f"Output file contents are incorrect: {lines}"


def test_cli_creates_log_with_correct_fields(folders):
    input_folder, output_folder, log_folder = folders

    test_file = os.path.join(input_folder, "test_file.csv")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")
        f.write("123|456|COVID-19|11/17/2024\n")
        f.write("789|101|Flu|11/16/2024\n")
        f.write("112|131|COVID-19|11/15/2024\n")

    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--input_folder",
            input_folder,
            "--output_folder",
            output_folder,
            "--log_folder",
            log_folder,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Check if a log file was created
    log_files = list(log_folder.glob("*.json"))  # Assuming log is a JSON file
    assert len(log_files) == 1, "Log file was not created or too many log files found."

    log_file = log_files[0]

    # Read the log file to verify its contents
    with open(log_file, "r", encoding="utf-8") as f:
        log_data = f.read()

    # Validate the presence of required keys in the log
    assert "run_id" in log_data, "log file does not contain 'run_id'."
    assert "input_file" in log_data, "log file does not contain 'input_file'."
    assert "output_folder" in log_data, "log file does not contain 'output_folder'."
    assert "timestamp" in log_data, "log file does not contain 'timestamp'."
    assert "version" in log_data, "log file does not contain 'version'."
    assert "result_message" in log_data, "log file does not contain 'result_message'."
