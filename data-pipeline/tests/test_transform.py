"""
Tests for the transformation of the data files
"""

# pylint: disable=missing-function-docstring

from pandas import DataFrame

from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus

from .fake_data import generate_fake_data


def test_transform_returns_data_frame():
    df_in = DataFrame()

    result = transform_data_from_aisr_to_infinite_campus(df_in)

    assert isinstance(result, DataFrame)


def test_transform_filters_columns():
    df_in = generate_fake_data(5)

    result = transform_data_from_aisr_to_infinite_campus(df_in)

    # Define the expected columns in the output dataframe
    expected_columns = ["id_1", "id_2", "vaccine_group_name", "vaccination_date"]

    # Ensure that the output dataframe contains only the expected columns
    assert list(result.columns) == expected_columns
