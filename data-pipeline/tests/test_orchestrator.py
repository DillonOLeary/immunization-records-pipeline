"""
Tests for the pipeline orchestration
"""

# pylint: disable=missing-function-docstring

# import pytest

import pandas as pd

from data_pipeline import DataPipeline


def test_pipeline_run():
    pipeline_instance = DataPipeline(
        data_loader=pd.DataFrame, transformation_function=lambda df: df
    )
    assert pipeline_instance.run() == "Data pipeline executed successfully"


def test_pipeline_calls_transform():
    called = False

    def mock_transformation_function(input_df: pd.DataFrame) -> pd.DataFrame:
        nonlocal called
        called = True
        return input_df

    pipeline_instance = DataPipeline(
        data_loader=pd.DataFrame, transformation_function=mock_transformation_function
    )
    pipeline_instance.run()
    assert called, "The transformation function was not called"


def test_pipeline_calls_data_loader():
    called = False

    def mock_data_loader() -> pd.DataFrame:
        nonlocal called
        called = True
        # Return a dummy DataFrame for testing purposes
        return pd.DataFrame({"id": [1, 2], "value": [10, 20]})

    pipeline_instance = DataPipeline(
        data_loader=mock_data_loader, transformation_function=lambda df: df
    )
    pipeline_instance.run()

    assert called, "The data loader function was not called"


def test_pipeline_passes_loaded_data_to_transformer():
    data_loaded = None

    def mock_data_loader() -> pd.DataFrame:
        # Return a dummy DataFrame for testing purposes
        return pd.DataFrame({"id": [1, 2], "value": [10, 20]})

    def mock_transformation_function(input_df: pd.DataFrame) -> pd.DataFrame:
        nonlocal data_loaded
        data_loaded = input_df  # Capture the DataFrame passed to the transformer
        return input_df  # No transformation in this mock

    # Initialize the pipeline with the mocked functions
    pipeline_instance = DataPipeline(
        data_loader=mock_data_loader,
        transformation_function=mock_transformation_function,
    )

    # Run the pipeline
    pipeline_instance.run()

    # Verify that the data passed to the transformation function is correct
    expected_data = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
    pd.testing.assert_frame_equal(data_loaded, expected_data)
