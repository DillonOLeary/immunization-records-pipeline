"""
Tests for the transformation of the data files
"""

# pylint: disable=missing-function-docstring

from pandas import DataFrame
from .fake_data import generate_fake_data

import data_pipeline.transform as transform


def test_transform_returns_data_frame():
    df_in = DataFrame()

    result = transform.transform_data_from_aisr_to_infinite_campus(df_in)

    assert isinstance(result, DataFrame)


def test_transform_filters_columns():
    df = generate_fake_data(5)
    
    print(df)

    expected_columns = ["id_1", "id_2", "vaccine_group_name", "vaccination_date"]
