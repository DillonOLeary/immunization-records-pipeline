"""
Tests for the transformation of the data files
"""

# pylint: disable=missing-function-docstring,duplicate-code,R0801

from datetime import datetime

import pytest

from src.minnesota_immunization_core.transform import (
    transform_data_from_aisr_to_infinite_campus,
)
from tests.test_data.test_data_generator import generate_test_data


def test_transform_filters_columns():
    df_in = generate_test_data(5)

    result = transform_data_from_aisr_to_infinite_campus(df_in)

    # Define the expected columns in the output dataframe
    expected_columns = ["id_1", "id_2", "vaccine_group_name", "vaccination_date"]

    # Ensure that the output dataframe contains only the expected columns
    assert list(result.columns) == expected_columns


def test_transform_formats_vaccination_date():
    # Generate fake data
    df_in = generate_test_data(5)

    # Transform the data
    result = transform_data_from_aisr_to_infinite_campus(df_in)

    # Ensure that the vaccination_date column is in MM/DD/YYYY format
    for date_str in result["vaccination_date"]:
        # Try to parse the date and check that it matches the expected format
        try:
            _ = datetime.strptime(date_str, "%m/%d/%Y")
        except ValueError:
            pytest.fail(
                f"Vaccination date '{date_str}' is not in the correct format MM/DD/YYYY"
            )
