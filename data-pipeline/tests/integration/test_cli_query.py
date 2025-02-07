"""
Test the CLI query command.
"""

from data_pipeline.aisr.actions import _put_file_to_s3
from data_pipeline.aisr.authenticate import login, logout
from data_pipeline.etl_workflow import run_aisr_workflow
from data_pipeline.pipeline_factory import (
    create_aisr_actions_for_school_bulk_query,
    create_aisr_workflow,
)

# from data_pipeline.pipeline_factory import create_aisr_workflow

# from data_pipeline.pipeline_factory import create_query_workflow

# from data_pipeline.pipeline_factory import create_query_function

# pylint: disable=missing-function-docstring

USERNAME = "test_user"
PASSWORD = "test_password"


def test_cli_query_can_upload_a_file(fastapi_server):
    """
    Test CLI by injecting dependencies.
    """
    # TODO put_file_to_s3 needs to be changed to a function that also gets the s3 url
    raise NotImplementedError(
        "this is an integration test, so I need to see if I can use the generated functions"
    )
    # action_list = generate_bulk_query_functions({})
    query_workflow = create_aisr_workflow(login, {}, logout)
    query_workflow(fastapi_server, USERNAME, PASSWORD)
