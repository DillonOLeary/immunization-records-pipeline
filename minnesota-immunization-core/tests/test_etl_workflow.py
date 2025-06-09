"""
Tests for the pipeline orchestration
"""

# pylint: disable=missing-function-docstring

import logging
import os
from unittest.mock import MagicMock

import pandas as pd
import requests

from minnesota_immunization_core.aisr.actions import AISRActionFailedError
from minnesota_immunization_core.aisr.authenticate import AISRAuthResponse
from minnesota_immunization_core.etl_workflow import (
    ETLExecutionFailureError,
    run_aisr_workflow,
    run_etl,
    run_etl_on_folder,
)


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


def test_run_etl_on_folder_creates_output_folder(test_env):
    input_folder, output_folder, _, _, _ = test_env

    run_etl_on_folder(input_folder, output_folder, lambda input_file, output_dir: "")

    # Assert that the output folder was created
    assert output_folder.exists(), "Output folder was not created"


def test_run_etl_on_folder_calls_etl_fn(test_env):
    input_folder, output_folder, _, _, _ = test_env

    test_file = input_folder / "test_file.csv"
    # File is already created by test_env fixture

    # Create a mock function and track its calls
    mock_etl_fn = MagicMock()
    run_etl_on_folder(input_folder, output_folder, mock_etl_fn)

    # Assert the mock function was called for each file in the input folder
    mock_etl_fn.assert_called_once_with(test_file, output_folder)


def test_run_etl_on_folder_no_input_files(test_env):
    input_folder, output_folder, _, _, _ = test_env

    # Clear input folder first
    for file in input_folder.glob("*"):
        file.unlink()

    # Run the ETL process with no files in input folder
    run_etl_on_folder(input_folder, output_folder, lambda input_file, output_dir: "")

    # Assert that no output files were created
    assert len(os.listdir(output_folder)) == 0, "Output files were created unexpectedly"


def test_run_etl_on_folder_handles_extract_exception(test_env, caplog):
    input_folder, output_folder, _, _, _ = test_env

    def failing_etl_fn(input_file, output_folder):
        raise ETLExecutionFailureError("Mock extract error")

    with caplog.at_level(logging.ERROR):
        run_etl_on_folder(input_folder, output_folder, failing_etl_fn)

    assert any(
        "ETL failed for file" in record.message and record.levelname == "ERROR"
        for record in caplog.records
    )


def test_aisr_runs_bulk_queries():
    called_query_1 = False
    called_query_2 = False

    def mock_query_function_1(session: requests.Session, access_token: str) -> None:
        # pylint: disable=unused-argument
        nonlocal called_query_1
        called_query_1 = True

    def mock_query_function_2(session: requests.Session, access_token: str) -> None:
        # pylint: disable=unused-argument
        nonlocal called_query_2
        called_query_2 = True

    run_aisr_workflow(
        login=lambda session: AISRAuthResponse(access_token="mocked-access-token"),
        aisr_actions=[mock_query_function_1, mock_query_function_2],
        logout=lambda session: None,
    )
    assert called_query_1 and called_query_2, "The query functions were not called"


def test_aisr_login_logout():
    login_called = False
    logout_called = False

    def mock_login(session: requests.Session) -> AISRAuthResponse:
        # pylint: disable=unused-argument
        nonlocal login_called
        login_called = True
        return AISRAuthResponse(access_token="mocked-access-token")

    def mock_logout(session: requests.Session) -> None:
        # pylint: disable=unused-argument
        nonlocal logout_called
        logout_called = True

    run_aisr_workflow(
        login=mock_login,
        aisr_actions=[],
        logout=mock_logout,
    )

    assert login_called, "Login function was not called"
    assert logout_called, "Logout function was not called"


def test_aisr_bulk_queries_handles_exceptions():
    def mock_query_function(session: requests.Session, access_token: str) -> None:
        raise AISRActionFailedError("Mock query failure")

    run_aisr_workflow(
        login=lambda session: AISRAuthResponse(access_token="mocked-access-token"),
        aisr_actions=[mock_query_function],
        logout=lambda session: None,
    )
