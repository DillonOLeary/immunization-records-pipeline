"""
Tests for CSV reading function
"""

# pylint: disable=missing-function-docstring

from pathlib import Path

from minnesota_immunization_core.extract import read_from_aisr_csv

INPUT_FILE_PATH = Path(".") / "tests" / "test_data" / "mock_aisr_download.csv"


def test_read_from_csv_has_id_1_column():
    df = read_from_aisr_csv(INPUT_FILE_PATH)

    assert "id_1" in df.columns, "'id_1' column is missing from the DataFrame"


def test_read_from_csv_has_vaccination_date_column():
    df = read_from_aisr_csv(INPUT_FILE_PATH)

    assert "vaccination_date" in df.columns, (
        "'vaccination_date' column is missing from the DataFrame"
    )


def test_read_from_csv_has_10000_rows():
    df = read_from_aisr_csv(INPUT_FILE_PATH)

    assert len(df) == 10000, f"Expected 10000 rows, but found {len(df)}"
