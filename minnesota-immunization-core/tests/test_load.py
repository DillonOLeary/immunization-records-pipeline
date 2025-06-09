"""
Tests for loading data to CSV
"""

# pylint: disable=missing-function-docstring

import pandas as pd

from minnesota_immunization_core.load import write_to_infinite_campus_csv

INPUT_FILE_NAME = "test_input.csv"
OUTPUT_FILE_NAME = f"t_{INPUT_FILE_NAME}"


def filename_generator(name):
    return f"t_{name}"


def test_write_to_csv_creates_file(tmp_path):
    test_df = pd.DataFrame({"id_1": [1], "vaccination_date": ["01/01/2022"]})

    write_to_infinite_campus_csv(test_df, tmp_path, INPUT_FILE_NAME, filename_generator)

    assert (tmp_path / f"t_{INPUT_FILE_NAME}").exists(), "CSV file was not created"


def test_write_to_csv_with_correct_separator(tmp_path):
    output_file = tmp_path / OUTPUT_FILE_NAME
    test_df = pd.DataFrame({"id_1": [1], "vaccination_date": ["01/01/2022"]})
    write_to_infinite_campus_csv(test_df, tmp_path, INPUT_FILE_NAME, filename_generator)

    with open(output_file, encoding="utf-8") as file:
        content = file.read()
    assert "," in content, "CSV file does not use a comma as the delimiter"


def test_write_to_csv_contains_expected_data(tmp_path):
    output_file = tmp_path / OUTPUT_FILE_NAME
    test_df = pd.DataFrame({"id_1": [1], "vaccination_date": ["01/01/2022"]})

    # Assuming write_to_infinite_campus_csv writes without headers
    write_to_infinite_campus_csv(test_df, tmp_path, INPUT_FILE_NAME, filename_generator)

    loaded_df = pd.read_csv(output_file, header=None)  # No header in the CSV

    # Verify data by comparing the number of rows and contents
    assert len(loaded_df) == len(test_df), (
        f"Expected {len(test_df)} rows, but found {len(loaded_df)}"
    )

    # Check that the actual data matches the expected data (ignoring column names)
    for expected_row, actual_row in zip(test_df.values, loaded_df.values, strict=False):
        assert list(expected_row) == list(actual_row), (
            f"Row mismatch: expected {expected_row}, but got {actual_row}"
        )
