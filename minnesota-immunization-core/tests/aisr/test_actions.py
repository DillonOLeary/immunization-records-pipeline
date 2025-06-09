"""
Tests for interacting with AISR
"""

# pylint: disable=missing-function-docstring

import pytest
import requests

from minnesota_immunization_core.aisr.actions import (
    AISRActionFailedError,
    S3UploadHeaders,
    SchoolQueryInformation,
    _get_put_url,
    _put_file_to_s3,
    bulk_query_aisr,
    download_vaccination_records,
    get_and_download_vaccination_records,
    get_latest_vaccination_records_url,
)

UPLOAD_FILE_NAME = "test_file.csv"


def test_can_get_put_url(fastapi_server):
    with requests.Session() as local_session:
        url = _get_put_url(
            local_session, fastapi_server, "test_access_token", "test-file.csv", 1234
        )

    assert url == f"{fastapi_server}/test-s3-put-location", "URL should be returned"


def test_upload_file_to_s3(fastapi_server, tmp_path):
    test_url = f"{fastapi_server}/test-s3-put-location"
    test_file_name = tmp_path / UPLOAD_FILE_NAME
    with open(test_file_name, "w", encoding="utf-8") as file:
        file.write("test data")

    test_headers = S3UploadHeaders("", "", "", "", "", "")

    with requests.Session() as local_session:
        response = _put_file_to_s3(
            local_session, test_url, test_headers, test_file_name
        )

    assert response.is_successful, "File upload should be successful"


def test_failed_upload_raises_exception(fastapi_server, tmp_path):
    test_url = f"{fastapi_server}/test-s3-put-location"
    test_file_name = tmp_path / UPLOAD_FILE_NAME
    with open(test_file_name, "w", encoding="utf-8") as file:
        file.write("")

    test_headers = S3UploadHeaders("", "", "", "", "", "")

    with requests.Session() as local_session:
        with pytest.raises(AISRActionFailedError):
            _put_file_to_s3(local_session, test_url, test_headers, test_file_name)


def test_complete_query_action(fastapi_server, tmp_path):
    test_file_name_and_path = tmp_path / UPLOAD_FILE_NAME
    with open(test_file_name_and_path, "w", encoding="utf-8") as file:
        file.write("test data")

    with requests.Session() as local_session:
        response = bulk_query_aisr(
            session=local_session,
            access_token="mocked-access-token",
            base_url=fastapi_server,
            query_info=SchoolQueryInformation(
                "name", "class", "id", "email@example.com", str(test_file_name_and_path)
            ),
        )

    assert response.is_successful, "File upload should be successful"


def test_get_latest_vaccination_records_url(fastapi_server):
    with requests.Session() as local_session:
        url = get_latest_vaccination_records_url(
            session=local_session,
            base_url=fastapi_server,
            access_token="mocked-access-token",
            school_id="1234",
        )

    assert url is not None, "URL should be returned"
    assert url == f"{fastapi_server}/test-s3-get-location", (
        "Correct URL should be returned"
    )


def test_download_vaccination_records(fastapi_server, tmp_path):
    test_output_path = tmp_path / "downloaded_vaccinations.csv"

    with requests.Session() as local_session:
        url = get_latest_vaccination_records_url(
            session=local_session,
            base_url=fastapi_server,
            access_token="mocked-access-token",
            school_id="1234",
        )

        response = download_vaccination_records(
            session=local_session,
            file_url=url,
            output_path=test_output_path,
        )

    assert response.is_successful, "File download should be successful"
    assert test_output_path.exists(), "Output file should exist"

    with open(test_output_path, encoding="utf-8") as file:
        content = file.read()

    assert "John Doe" in content, "Downloaded content should contain expected data"


def test_get_and_download_vaccination_records(fastapi_server, tmp_path):
    test_output_path = tmp_path / "downloaded_vaccinations_combined.csv"

    with requests.Session() as local_session:
        response = get_and_download_vaccination_records(
            session=local_session,
            access_token="mocked-access-token",
            base_url=fastapi_server,
            school_id="1234",
            output_path=test_output_path,
        )

    assert response.is_successful, "File download should be successful"
    assert test_output_path.exists(), "Output file should exist"

    with open(test_output_path, encoding="utf-8") as file:
        content = file.read()

    assert "John Doe" in content, "Downloaded content should contain expected data"
