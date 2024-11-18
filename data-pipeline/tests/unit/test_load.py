"""
Tests for loading data to CSV
"""

# pylint: disable=missing-function-docstring

import pandas as pd
from data_pipeline.load import write_to_infinite_campus_csv

INPUT_FILE_NAME = "test_input.csv"
OUTPUT_FILE_NAME = f"transformed_{INPUT_FILE_NAME}"


def test_write_to_csv_creates_file(tmp_path):
    test_df = pd.DataFrame({"id_1": [1], "vaccination_date": ["01/01/2022"]})

    write_to_infinite_campus_csv(test_df, tmp_path, INPUT_FILE_NAME)

    assert (tmp_path / f"transformed_{INPUT_FILE_NAME}").exists(), "CSV file was not created"


def test_write_to_csv_with_correct_separator(tmp_path):
    output_file = tmp_path / OUTPUT_FILE_NAME
    test_df = pd.DataFrame({"id_1": [1], "vaccination_date": ["01/01/2022"]})
    write_to_infinite_campus_csv(test_df, tmp_path, INPUT_FILE_NAME)

    with open(output_file, "r", encoding="utf-8") as file:
        content = file.read()
    assert "," in content, "CSV file does not use a comma as the delimiter"


def test_write_to_csv_contains_expected_data(tmp_path):
    output_file = tmp_path / OUTPUT_FILE_NAME
    test_df = pd.DataFrame({"id_1": [1], "vaccination_date": ["01/01/2022"]})

    write_to_infinite_campus_csv(test_df, tmp_path, INPUT_FILE_NAME)

    loaded_df = pd.read_csv(output_file)
    assert "id_1" in loaded_df.columns, "'id_1' column is missing in the output CSV"
    assert (
        "vaccination_date" in loaded_df.columns
    ), "'vaccination_date' column is missing in the output CSV"
    assert len(loaded_df) == len(
        test_df
    ), f"Expected {len(test_df)} rows, but found {len(loaded_df)}"
