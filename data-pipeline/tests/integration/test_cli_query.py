"""
Test the CLI query command.
"""

from data_pipeline.aisr.actions import SchoolQueryInformation
from data_pipeline.aisr.authenticate import login, logout
from data_pipeline.pipeline_factory import (
    create_aisr_actions_for_school_bulk_queries,
    create_aisr_workflow,
)

USERNAME = "test_user"
PASSWORD = "test_password"


def test_cli_query_can_upload_a_file(fastapi_server, tmp_path):
    """
    Test CLI by injecting dependencies.
    """
    auth_base_url = f"{fastapi_server}/mock-auth-server"
    aisr_base_url = fastapi_server
    bulk_query_file = tmp_path / "bulk_query.csv"

    with open(bulk_query_file, "w", encoding="utf-8") as file:
        file.write("body")

    school_info_list = [
        SchoolQueryInformation(
            "test_school1", "N", "test_id1", "test_email1", str(bulk_query_file)
        ),
    ]
    action_list = create_aisr_actions_for_school_bulk_queries(school_info_list)
    query_workflow = create_aisr_workflow(login, action_list, logout)
    query_workflow(auth_base_url, aisr_base_url, USERNAME, PASSWORD)
