"""
Tests for MIIC quering
"""

# pylint: disable=missing-function-docstring

from data_pipeline.pipeline_factory import use_web_driver
from data_pipeline.query import login

TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"
TEST_ROW_ID = "test_row_id"


def test_login_return_row_element(fastapi_server):
    with use_web_driver(fastapi_server) as driver:
        result = login(
            web_driver=driver, username=TEST_USERNAME, password=TEST_PASSWORD
        )

    assert result.message == "Logged in", "Message should be 'Logged in'"
    assert result.is_successful, "Log in should be successful"
