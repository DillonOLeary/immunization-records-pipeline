"""
Tests for CSV reading function
"""

# pylint: disable=missing-function-docstring


# return lambda: pd.read_csv(file_path, sep="|")

from pathlib import Path

from data_pipeline.csv_read import read_from_aisr_csv


def test_read_from_csv_has_id_1_column():
    file_path = Path("tests/mock_data/mock_aisr_download.csv")

    df = read_from_aisr_csv(file_path)

    assert "id_1" in df.columns, "'id_1' column is missing from the DataFrame"


def test_read_from_csv_has_vaccination_date_column():
    file_path = Path("tests/mock_data/mock_aisr_download.csv")

    df = read_from_aisr_csv(file_path)

    assert (
        "vaccination_date" in df.columns
    ), "'vaccination_date' column is missing from the DataFrame"


def test_read_from_csv_has_10000_rows():
    file_path = Path("tests/mock_data/mock_aisr_download.csv")

    df = read_from_aisr_csv(file_path)

    assert len(df) == 10000, f"Expected 10000 rows, but found {len(df)}"
