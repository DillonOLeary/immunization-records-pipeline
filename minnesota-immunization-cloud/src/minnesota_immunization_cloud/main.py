"""
Cloud Functions for Minnesota Immunization Pipeline
Integrates with AISR system for real immunization data processing
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from google.cloud import secretmanager, storage
from minnesota_immunization_core.aisr.actions import SchoolQueryInformation
from minnesota_immunization_core.aisr.authenticate import login, logout
from minnesota_immunization_core.etl_workflow import run_etl_on_folder
from minnesota_immunization_core.extract import read_from_aisr_csv
from minnesota_immunization_core.load import write_to_infinite_campus_csv
from minnesota_immunization_core.pipeline_factory import (
    create_aisr_actions_for_school_bulk_queries,
    create_aisr_download_actions,
    create_aisr_workflow,
    create_file_to_file_etl_pipeline,
)
from minnesota_immunization_core.transform import (
    transform_data_from_aisr_to_infinite_campus,
)


def get_storage_client():
    """Get Google Cloud Storage client"""
    return storage.Client()


def get_secret(secret_name: str) -> str:
    """Retrieve secret from Google Cloud Secret Manager"""
    client = secretmanager.SecretManagerServiceClient()
    project_id = os.environ.get("GCP_PROJECT", "mn-immun-bd9001")
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"

    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def upload_to_storage(bucket_name: str, blob_name: str, data: str):
    """Upload data to Google Cloud Storage"""
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(data, content_type="text/plain")
    print(f"Uploaded to gs://{bucket_name}/{blob_name}")


def upload_file_to_storage(bucket_name: str, blob_name: str, file_path: str):
    """Upload file to Google Cloud Storage"""
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(file_path)
    print(f"Uploaded file to gs://{bucket_name}/{blob_name}")


def download_from_storage(bucket_name: str, blob_name: str, destination_path: str):
    """Download file from Google Cloud Storage"""
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(destination_path)
    print(f"Downloaded gs://{bucket_name}/{blob_name} to {destination_path}")


def upload_handler(event, context):
    """
    Cloud Function triggered by Pub/Sub (Monday scheduler)
    Submits bulk queries to AISR for immunization records
    """
    print("🚀 Upload function triggered!")

    # Get configuration from environment
    bucket_name = os.environ["DATA_BUCKET"]
    username = get_secret(os.environ["AISR_USERNAME_SECRET"])
    password = get_secret(os.environ["AISR_PASSWORD_SECRET"])

    # API URLs
    # FIXME - use mock server for testing. These should be configurable via env vars
    # auth_url = "https://minnesota-immunization-mock-7f3imvzzwq-uc.a.run.app/mock-auth-server"
    # api_url = "https://minnesota-immunization-mock-7f3imvzzwq-uc.a.run.app"
    auth_url = "https://authenticator4.web.health.state.mn.us"
    api_url = "https://aisr-api.web.health.state.mn.us"

    # Download school configuration from storage
    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)
    config_blob = bucket.blob("config/config.json")

    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = Path(temp_dir) / "config.json"
        config_blob.download_to_filename(str(config_file))

        with open(config_file) as f:
            config = json.load(f)

        # Create SchoolQueryInformation objects
        school_info_list = []
        for school in config["schools"]:
            # Download query file from storage using the path specified in config
            query_blob = bucket.blob(school["bulk_query_file"])
            query_file = Path(temp_dir) / f"{school['name']}_query.csv"
            query_blob.download_to_filename(str(query_file))

            school_info = SchoolQueryInformation(
                school_name=school["name"],
                classification=school["classification"],
                school_id=school["id"],
                email_contact=school["email"],
                query_file_path=str(query_file),
            )
            school_info_list.append(school_info)

        # Create bulk query actions using pipeline factory
        action_list = create_aisr_actions_for_school_bulk_queries(school_info_list)

        # Create AISR workflow with injected dependencies
        query_workflow = create_aisr_workflow(login, action_list, logout)

        # Execute bulk query workflow
        print("🔄 Starting AISR bulk queries...")
        query_workflow(auth_url, api_url, username, password)

        # Store completion status
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        results_data = {
            "upload_time": datetime.now().isoformat(),
            "schools_processed": len(school_info_list),
            "status": "completed",
        }

        results_filename = f"uploads/{timestamp}_bulk_query_results.json"
        upload_to_storage(
            bucket_name, results_filename, json.dumps(results_data, indent=2)
        )

        print(f"📤 Upload completed: {len(school_info_list)} schools processed")
        return {"status": "success", "schools_processed": len(school_info_list)}


def download_handler(event, context):
    """
    Cloud Function triggered by Pub/Sub (Wednesday scheduler)
    Downloads vaccination records from AISR and transforms them via ETL pipeline
    """
    print("📥 Download function triggered!")

    # Get configuration from environment
    bucket_name = os.environ["DATA_BUCKET"]
    username = get_secret(os.environ["AISR_USERNAME_SECRET"])
    password = get_secret(os.environ["AISR_PASSWORD_SECRET"])

    # API URLs
    auth_url = "https://authenticator4.web.health.state.mn.us"
    api_url = "https://aisr-api.web.health.state.mn.us"

    # Download school configuration from storage
    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)
    config_blob = bucket.blob("config/config.json")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create directories
        input_folder = temp_path / "input"
        output_folder = temp_path / "output"
        input_folder.mkdir(exist_ok=True)
        output_folder.mkdir(exist_ok=True)

        # Download and parse school configuration
        config_file = temp_path / "config.json"
        config_blob.download_to_filename(str(config_file))

        with open(config_file) as f:
            config = json.load(f)

        # Create SchoolQueryInformation objects
        school_info_list = []
        for school in config["schools"]:
            school_info = SchoolQueryInformation(
                school_name=school["name"],
                classification=school["classification"],
                school_id=school["id"],
                email_contact=school["email"],
                query_file_path="",  # Not needed for downloads
            )
            school_info_list.append(school_info)

        # Create download actions using pipeline factory
        download_actions = create_aisr_download_actions(
            school_info_list=school_info_list, output_folder=input_folder
        )

        # Create AISR download workflow with injected dependencies
        download_workflow = create_aisr_workflow(
            login=login, aisr_function_list=download_actions, logout=logout
        )

        # Execute download workflow
        print("🔄 Starting AISR vaccination record download...")
        download_workflow(auth_url, api_url, username, password)

        # Create ETL pipeline with injected dependencies
        etl_pipeline = create_file_to_file_etl_pipeline(
            extract=read_from_aisr_csv,
            transform=transform_data_from_aisr_to_infinite_campus,
            load=write_to_infinite_campus_csv,
        )

        # Run ETL transformation on downloaded files
        print("🔄 Starting ETL transformation...")
        run_etl_on_folder(
            input_folder=input_folder,
            output_folder=output_folder,
            etl_fn=etl_pipeline,
        )

        # Upload transformed files back to storage
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_files = list(output_folder.glob("*.csv"))

        for output_file in output_files:
            blob_name = f"output/{timestamp}_{output_file.name}"
            upload_file_to_storage(bucket_name, blob_name, str(output_file))

        # Store completion metadata
        metadata = {
            "download_time": datetime.now().isoformat(),
            "schools_processed": len(school_info_list),
            "files_transformed": len(output_files),
            "status": "completed",
        }

        metadata_filename = f"downloads/{timestamp}_download_metadata.json"
        upload_to_storage(
            bucket_name, metadata_filename, json.dumps(metadata, indent=2)
        )

        print(f"📥 Download and ETL completed: {len(output_files)} files processed")
        return {
            "status": "success",
            "schools_processed": len(school_info_list),
            "files_transformed": len(output_files),
        }


if __name__ == "__main__":
    print("🧪 Testing functions locally...")
    print("⚠️  Note: Local testing requires environment variables:")
    print("   - DATA_BUCKET")
    print("   - AISR_USERNAME_SECRET")
    print("   - AISR_PASSWORD_SECRET")
    print("   - GCP_PROJECT (optional)")

    # Mock event and context
    mock_event = {"data": "eyJhY3Rpb24iOiAidGVzdCJ9"}
    mock_context = type("MockContext", (), {"timestamp": "2023-01-01T00:00:00Z"})()

    print("\n--- Testing Upload Function (AISR Bulk Query) ---")
    result = upload_handler(mock_event, mock_context)
    print(f"Upload result: {result}")

    print("\n--- Testing Download Function (AISR Download + ETL) ---")
    result = download_handler(mock_event, mock_context)
    print(f"Download result: {result}")

    print("\n✅ Local testing completed!")
