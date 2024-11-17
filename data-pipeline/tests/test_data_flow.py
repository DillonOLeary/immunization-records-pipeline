"""
Tests for the pipeline orchestration
"""

# pylint: disable=missing-function-docstring


import pandas as pd

from data_pipeline.data_flow import run_pipeline


def test_pipeline_runs():
    message = run_pipeline(
        extract_function=pd.DataFrame, transform_function=lambda df: df
    )
    assert message == "Data pipeline executed successfully"


def test_pipeline_calls_transform_function():
    called = False

    def mock_transform_function(input_df: pd.DataFrame) -> pd.DataFrame:
        nonlocal called
        called = True
        return input_df

    run_pipeline(
        extract_function=pd.DataFrame,
        transform_function=mock_transform_function,
    )
    assert called, "The transform function was not called"


def test_pipeline_calls_data_extract_function():
    called = False

    def mock_extract_function() -> pd.DataFrame:
        nonlocal called
        called = True
        # Return a dummy DataFrame for testing purposes
        return pd.DataFrame({"id": [1, 2], "value": [10, 20]})

    run_pipeline(
        extract_function=mock_extract_function, transform_function=lambda df: df
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

    run_pipeline(
        extract_function=mock_extract_function,
        transform_function=mock_transform_function,
    )

    # Verify that the data passed to the transform function is correct
    expected_data = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
    pd.testing.assert_frame_equal(data_extracted, expected_data)
