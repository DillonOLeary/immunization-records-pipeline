"""
Unit tests for the pipeline factory
"""

import requests

from minnesota_immunization_core.aisr.authenticate import login, logout
from minnesota_immunization_core.pipeline_factory import (
    SchoolQueryInformation,
    create_aisr_actions_for_school_bulk_queries,
    create_aisr_download_actions,
    create_aisr_workflow,
)

# pylint: disable=missing-function-docstring

USERNAME = "test_user"
PASSWORD = "test_password"


def test_generate_bulk_query_functions(fastapi_server, tmp_path):
    file1 = tmp_path / "bulk_query_1.csv"
    file2 = tmp_path / "bulk_query_2.csv"

    with open(file1, "w", encoding="utf-8") as file:
        file.write("body")

    with open(file2, "w", encoding="utf-8") as file:
        file.write("body")

    school_information_list = [
        SchoolQueryInformation(
            "test_school",
            "N",
            "test_id",
            "test_email",
            str(file1),
        ),
        SchoolQueryInformation(
            "test_school_2",
            "P",
            "test_id_2",
            "test_email_2",
            str(file2),
        ),
    ]

    query_functions = create_aisr_actions_for_school_bulk_queries(
        school_information_list
    )

    # should be able to run the query functions with no exceptions
    with requests.Session() as session:
        for query_function in query_functions:
            query_function(
                session,
                "mocked-access-token",
                fastapi_server,
            )


def test_generate_download_functions(fastapi_server, tmp_path):
    school_information_list = [
        SchoolQueryInformation(
            "test_school",
            "N",
            "test_id",
            "test_email",
            "dummy_file_path",
        ),
        SchoolQueryInformation(
            "test_school_2",
            "P",
            "test_id_2",
            "test_email_2",
            "dummy_file_path",
        ),
    ]

    # Create download folder
    download_folder = tmp_path / "downloads"
    download_folder.mkdir(exist_ok=True)

    # Generate download functions
    download_functions = create_aisr_download_actions(
        school_info_list=school_information_list, output_folder=download_folder
    )

    # Check that we got the right number of functions
    assert len(download_functions) == 2, "Should create one function per school"

    # Test the functions
    with requests.Session() as session:
        for download_function in download_functions:
            # This should call get_and_download_vaccination_records with the mock server
            download_function(
                session,
                "mocked-access-token",
                fastapi_server,
            )

    # Verify files were created - they should follow our naming pattern
    files = list(download_folder.glob("vaccinations_*.csv"))
    assert len(files) == 2, "Should create one file per school"

    # Check file contents
    for file_path in files:
        # Verify the filename pattern
        assert (
            "vaccinations_test_school_" in file_path.name
            or "vaccinations_test_school_2_" in file_path.name
        )

        with open(file_path, encoding="utf-8") as f:
            content = f.read()
            # The mock server returns content with "John Doe"
            assert "John Doe" in content, "Downloaded content should match expected"


def test_create_callable_aisr_workflow(fastapi_server):
    auth_base_url = f"{fastapi_server}/mock-auth-server"
    aisr_base_url = fastapi_server

    query_workflow = create_aisr_workflow(login, {}, logout)
    query_workflow(auth_base_url, aisr_base_url, USERNAME, PASSWORD)


def test_aisr_workflow_runs_actions_independently(fastapi_server):
    auth_base_url = f"{fastapi_server}/mock-auth-server"
    aisr_base_url = fastapi_server

    called_action_1 = False
    called_action_2 = False

    def mock_action_function_1(
        session: requests.Session, access_token: str, base_url: str
    ) -> None:
        # pylint: disable=unused-argument
        nonlocal called_action_1
        called_action_1 = True

    def mock_action_function_2(
        session: requests.Session, access_token: str, base_url: str
    ) -> None:
        # pylint: disable=unused-argument
        nonlocal called_action_2
        called_action_2 = True

    query_workflow = create_aisr_workflow(
        login, [mock_action_function_1, mock_action_function_2], logout
    )
    query_workflow(auth_base_url, aisr_base_url, USERNAME, PASSWORD)

    assert called_action_1, "Action function 1 was not called"
    assert called_action_2, "Action function 2 was not called"
