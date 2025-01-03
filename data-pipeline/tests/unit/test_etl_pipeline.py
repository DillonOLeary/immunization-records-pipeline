"""
Tests for the pipeline orchestration
"""

# pylint: disable=missing-function-docstring


import os
from unittest.mock import MagicMock

import pandas as pd
from data_pipeline.etl_workflow import run_etl, run_etl_on_folder


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


def test_run_etl_on_folder_creates_output_folder(folders):
    input_folder, output_folder, _ = folders

    run_etl_on_folder(input_folder, output_folder, lambda: "")

    # Assert that the output folder was created
    assert output_folder.exists(), "Output folder was not created"


def test_run_etl_on_folder_calls_etl_fn(folders):
    input_folder, output_folder, _ = folders

    test_file = input_folder / "test_file.csv"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")

    # Create a mock function and track its calls
    mock_etl_fn = MagicMock()
    run_etl_on_folder(input_folder, output_folder, mock_etl_fn)

    # Assert the mock function was called for each file in the input folder
    mock_etl_fn.assert_called_once_with(test_file, output_folder)


def test_run_etl_on_folder_no_input_files(folders):
    input_folder, output_folder, _ = folders

    # Run the ETL process with no files in input folder
    run_etl_on_folder(input_folder, output_folder, lambda: "")

    # Assert that no output files were created
    assert len(os.listdir(output_folder)) == 0, "Output files were created unexpectedly"
