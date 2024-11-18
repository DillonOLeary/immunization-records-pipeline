"""
Tests for the pipeline orchestration
"""

# pylint: disable=missing-function-docstring


import pandas as pd
from data_pipeline.etl_pipeline import run_etl


def test_pipeline_runs():
    message = run_etl(
        extract=pd.DataFrame,
        transform=lambda df: df,
        load=lambda df: None,
    )
    assert message == "Data pipeline executed successfully"


def test_pipeline_calls_transform_function():
    called = False

    def mock_transform_function(input_df: pd.DataFrame) -> pd.DataFrame:
        nonlocal called
        called = True
        return input_df

    run_etl(
        extract=pd.DataFrame,
        transform=mock_transform_function,
        load=lambda df: None,
    )
    assert called, "The transform function was not called"


def test_pipeline_calls_data_extract_function():
    called = False

    def mock_extract_function() -> pd.DataFrame:
        nonlocal called
        called = True
        # Return a dummy DataFrame for testing purposes
        return pd.DataFrame({"id": [1, 2], "value": [10, 20]})

    run_etl(
        extract=mock_extract_function,
        transform=lambda df: df,
        load=lambda df: None,
    )

    assert called, "The extract function was not called"


def test_pipeline_passes_extracted_data_to_transformer():
    data_extracted = None

    def mock_extract_function() -> pd.DataFrame:
        # Return a dummy DataFrame for testing purposes
        return pd.DataFrame({"id": [1, 2], "value": [10, 20]})

    def mock_transform_function(input_df: pd.DataFrame) -> pd.DataFrame:
        nonlocal data_extracted
        data_extracted = input_df  # Capture the DataFrame passed to the transformer
        return input_df  # No transformation in this mock

    run_etl(
        extract=mock_extract_function,
        transform=mock_transform_function,
        load=lambda df: None,
    )

    # Verify that the data passed to the transform function is correct
    expected_data = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
    pd.testing.assert_frame_equal(data_extracted, expected_data)


def test_pipeline_calls_data_load_function():
    called = False

    def mock_load_function(input_df: pd.DataFrame) -> None:
        # pylint: disable=unused-argument
        nonlocal called
        called = True

    run_etl(
        extract=pd.DataFrame,
        transform=lambda df: df,
        load=mock_load_function,
    )

    assert called, "The load function was not called"
