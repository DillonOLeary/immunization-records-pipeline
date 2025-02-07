"""
Unit tests for the pipeline factory
"""

import requests
from data_pipeline.aisr.authenticate import AISRAuthResponse, login, logout
from data_pipeline.pipeline_factory import (
    SchoolQueryInformation,
    create_aisr_actions_for_school_bulk_query,
    create_aisr_workflow,
)

# pylint: disable=missing-function-docstring

USERNAME = "test_user"
PASSWORD = "test_password"


def test_generate_bulk_query_functions(fastapi_server):
    school_information_dict = {
        "test_school_id_123": SchoolQueryInformation(
            "test_school", "N", "test_id", "test_email", None
        ),
        "test_school_id_456": SchoolQueryInformation(
            "test_school_2", "P", "test_id_2", "test_email_2", None
        ),
    }

    query_functions = create_aisr_actions_for_school_bulk_query(school_information_dict)

    # should be able to run the query functions with no exceptions
    with requests.Session() as session:
        for query_function in query_functions:
            query_function(session, fastapi_server)


def test_create_callable_aisr_workflow(fastapi_server):
    query_workflow = create_aisr_workflow(login, {}, logout)
    query_workflow(fastapi_server, USERNAME, PASSWORD)


def test_aisr_workflow_runs_actions_independently(fastapi_server):
    called_action_1 = False
    called_action_2 = False

    def mock_action_function_1(
        session: requests.Session, aisr_response: AISRAuthResponse, base_url: str
    ) -> None:
        # pylint: disable=unused-argument
        nonlocal called_action_1
        called_action_1 = True

    def mock_action_function_2(
        session: requests.Session, aisr_response: AISRAuthResponse, base_url: str
    ) -> None:
        # pylint: disable=unused-argument
        nonlocal called_action_2
        called_action_2 = True

    query_workflow = create_aisr_workflow(
        login, [mock_action_function_1, mock_action_function_2], logout
    )
    query_workflow(fastapi_server, USERNAME, PASSWORD)

    assert called_action_1, "Action function 1 was not called"
    assert called_action_2, "Action function 2 was not called"
