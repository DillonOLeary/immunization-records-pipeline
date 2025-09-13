"""
Tests for incremental vaccination processing functionality
"""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from minnesota_immunization_cloud.main import (
    combine_vaccination_dataframes,
    compute_vaccination_diff,
    load_all_known_vaccinations,
)


def test_combine_vaccination_dataframes_empty_list():
    """Test combining with empty list returns empty DataFrame"""
    result = combine_vaccination_dataframes([])
    assert result.empty
    assert list(result.columns) == []


def test_combine_vaccination_dataframes_valid_files():
    """Test combining valid vaccination CSV files"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create test CSV files
        file1 = temp_path / "school1.csv"
        file2 = temp_path / "school2.csv"

        # Sample data in IC format (no headers) - numeric IDs like real data
        data1 = pd.DataFrame(
            [
                [12345, 678901, "MMR", "01/15/2024"],
                [12346, 678902, "Polio", "02/01/2024"],
            ]
        )
        data2 = pd.DataFrame(
            [
                [12347, 678903, "DPT", "01/20/2024"],
            ]
        )

        data1.to_csv(file1, index=False, header=False)
        data2.to_csv(file2, index=False, header=False)

        # Test combination
        result = combine_vaccination_dataframes([file1, file2])

        assert len(result) == 3
        assert list(result.columns) == [
            "id_1",
            "id_2",
            "vaccine_group_name",
            "vaccination_date",
        ]
        assert result.iloc[0]["id_1"] == 12345
        assert result.iloc[2]["vaccine_group_name"] == "DPT"


def test_combine_vaccination_dataframes_with_duplicates():
    """Test combining files with duplicate records"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create test CSV files with duplicates
        file1 = temp_path / "school1.csv"
        file2 = temp_path / "school2.csv"

        # Same record in both files
        data1 = pd.DataFrame(
            [
                [12345, 678901, "MMR", "01/15/2024"],
                [12346, 678902, "Polio", "02/01/2024"],
            ]
        )
        data2 = pd.DataFrame(
            [
                [12345, 678901, "MMR", "01/15/2024"],  # Duplicate
                [12347, 678903, "DPT", "01/20/2024"],
            ]
        )

        data1.to_csv(file1, index=False, header=False)
        data2.to_csv(file2, index=False, header=False)

        result = combine_vaccination_dataframes([file1, file2])

        # Should remove duplicates
        assert len(result) == 3
        unique_id1_values = result["id_1"].unique()
        assert 12345 in unique_id1_values
        assert (
            len(result[result["id_1"] == 12345]) == 1
        )  # Only one instance of duplicate


def test_compute_vaccination_diff_empty_current():
    """Test diff computation with empty current data"""
    current = pd.DataFrame(
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"]
    )
    known = pd.DataFrame(
        [[12345, 678901, "MMR", "01/15/2024"]],
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"],
    )

    result = compute_vaccination_diff(current, known)
    assert result.empty


def test_compute_vaccination_diff_empty_known():
    """Test diff computation with empty known data"""
    current = pd.DataFrame(
        [[12345, 678901, "MMR", "01/15/2024"], [12346, 678902, "Polio", "02/01/2024"]],
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"],
    )
    known = pd.DataFrame(
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"]
    )

    result = compute_vaccination_diff(current, known)
    assert len(result) == 2
    assert result.equals(current)


def test_compute_vaccination_diff_some_new_records():
    """Test diff computation with some new records"""
    current = pd.DataFrame(
        [
            [12345, 678901, "MMR", "01/15/2024"],  # Known
            [12346, 678902, "Polio", "02/01/2024"],  # New
            [12347, 678903, "DPT", "01/20/2024"],  # New
        ],
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"],
    )

    known = pd.DataFrame(
        [
            [12345, 678901, "MMR", "01/15/2024"],  # Already known
        ],
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"],
    )

    result = compute_vaccination_diff(current, known)

    assert len(result) == 2
    assert 12345 not in result["id_1"].values  # Known record should not be in diff
    assert 12346 in result["id_1"].values  # New record should be in diff
    assert 12347 in result["id_1"].values  # New record should be in diff


def test_compute_vaccination_diff_no_new_records():
    """Test diff computation with no new records"""
    data = pd.DataFrame(
        [[12345, 678901, "MMR", "01/15/2024"], [12346, 678902, "Polio", "02/01/2024"]],
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"],
    )

    # Current and known are identical
    result = compute_vaccination_diff(data, data)
    assert result.empty


def test_load_all_known_vaccinations_no_cloud_storage():
    """Test loading known vaccinations when cloud storage is not available"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Should return empty DataFrame when cloud storage not available
        result = load_all_known_vaccinations("test-bucket", temp_path)

        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == [
            "id_1",
            "id_2",
            "vaccine_group_name",
            "vaccination_date",
        ]
        assert result.empty


def test_combine_vaccination_dataframes_invalid_files():
    """Test combining with files that have insufficient columns"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create file with insufficient columns
        file1 = temp_path / "invalid.csv"
        data1 = pd.DataFrame([[12345, 678901]])  # Only 2 columns

        # Create valid file
        file2 = temp_path / "valid.csv"
        data2 = pd.DataFrame([[12347, 678903, "DPT", "01/20/2024"]])

        data1.to_csv(file1, index=False, header=False)
        data2.to_csv(file2, index=False, header=False)

        result = combine_vaccination_dataframes([file1, file2])

        # Should only include valid file
        assert len(result) == 1
        assert result.iloc[0]["id_1"] == 12347


def test_vaccination_key_generation():
    """Test that different records generate different keys for comparison"""
    data1 = pd.DataFrame(
        [
            [12345, 678901, "MMR", "01/15/2024"],
            [12345, 678901, "MMR", "01/16/2024"],  # Same person, different date
            [12345, 678901, "Polio", "01/15/2024"],  # Same person, different vaccine
        ],
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"],
    )

    data2 = pd.DataFrame(
        [
            [
                12345,
                678901,
                "MMR",
                "01/15/2024",
            ],  # Exact match - should be filtered out
        ],
        columns=["id_1", "id_2", "vaccine_group_name", "vaccination_date"],
    )

    result = compute_vaccination_diff(data1, data2)

    # Should return 2 records (different date and different vaccine)
    assert len(result) == 2
    dates = result["vaccination_date"].tolist()
    vaccines = result["vaccine_group_name"].tolist()

    assert "01/16/2024" in dates
    assert "Polio" in vaccines
    assert "01/15/2024" in dates  # For the Polio record


if __name__ == "__main__":
    pytest.main([__file__])
