"""
Integration tests for AISR vaccination records extraction.
"""

import pandas as pd
import requests
from data_pipeline.aisr.actions import (
    download_vaccination_records,
    get_latest_vaccination_records_url,
)
from data_pipeline.aisr.authenticate import login, logout
from data_pipeline.extract import read_from_aisr_csv

USERNAME = "test_user"
PASSWORD = "test_password"


def test_aisr_can_download_vaccination_records(fastapi_server, tmp_path):
    """
    Test downloading vaccination records from AISR.

    This test verifies the complete flow:
    1. Log in to AISR
    2. Get the URL for the latest vaccination records
    3. Download the records to a local file
    4. Verify the file can be processed with the extract function
    """
    auth_base_url = f"{fastapi_server}/mock-auth-server"
    aisr_base_url = fastapi_server
    school_id = "1234"
    output_file = tmp_path / "downloaded_vaccinations.csv"

    with requests.Session() as session:
        auth_response = login(session, auth_base_url, USERNAME, PASSWORD)

        records_url = get_latest_vaccination_records_url(
            session, aisr_base_url, auth_response, school_id
        )

        assert records_url is not None, "Failed to get vaccination records URL"

        download_response = download_vaccination_records(
            session, records_url, output_file
        )

        assert download_response.is_successful, "Failed to download vaccination records"
        assert output_file.exists(), "Downloaded file does not exist"

        df = read_from_aisr_csv(output_file)
        assert isinstance(
            df, pd.DataFrame
        ), "Failed to parse downloaded file as DataFrame"
        assert not df.empty, "DataFrame is empty"
        assert "John Doe" in df.to_string(), "Expected data not found in DataFrame"

        logout(session, auth_base_url)
