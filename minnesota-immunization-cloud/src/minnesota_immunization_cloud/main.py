"""
Cloud Functions for Minnesota Immunization Pipeline
Integrates with AISR system for real immunization data processing
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

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

from .cloud_storage import get_storage_client, upload_file_to_storage, upload_to_storage
from .google_drive import upload_to_google_drive, upload_to_school_folder
from .secrets import get_secret


def load_config_from_storage(bucket_name: str, temp_dir: Path) -> dict:
    """Load configuration from storage"""
    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)
    config_blob = bucket.blob("config/config.json")

    config_file = temp_dir / "config.json"
    config_blob.download_to_filename(str(config_file))

    with open(config_file) as f:
        return json.load(f)


def create_school_info_list(
    config: dict, bucket_name: str, temp_dir: Path, include_query_files: bool = True
) -> list[SchoolQueryInformation]:
    """Create SchoolQueryInformation objects from configuration"""
    school_info_list = []

    if include_query_files:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)

    for school in config["schools"]:
        query_file_path = ""

        if include_query_files:
            query_blob = bucket.blob(school["bulk_query_file"])
            query_file = temp_dir / f"{school['name']}_query.csv"
            query_blob.download_to_filename(str(query_file))
            query_file_path = str(query_file)

        school_info = SchoolQueryInformation(
            school_name=school["name"],
            classification=school["classification"],
            school_id=school["id"],
            email_contact=school["email"],
            query_file_path=query_file_path,
        )
        school_info_list.append(school_info)

    return school_info_list


def get_aisr_credentials() -> tuple[str, str]:
    """Get AISR username and password from secrets"""
    return get_secret("aisr-username"), get_secret("aisr-password")


def get_aisr_urls_from_config(config: dict) -> tuple[str, str]:
    """Get AISR API URLs from configuration"""
    api_config = config["api"]
    return api_config["auth_base_url"], api_config["aisr_api_base_url"]


def upload_files_to_destinations(
    output_files: list[Path],
    bucket_name: str,
    timestamp: str,
    school_info_list: list[SchoolQueryInformation],
) -> None:
    """Upload transformed files to both Cloud Storage and Google Drive organized by school"""
    for output_file in output_files:
        blob_name = f"output/{timestamp}_{output_file.name}"
        upload_file_to_storage(bucket_name, blob_name, str(output_file))

        drive_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        if drive_folder_id:
            try:
                # Find school by matching filename pattern
                school_name = None
                for school in school_info_list:
                    # Check if filename contains the school name (with underscores)
                    clean_school_name = school.school_name.replace(" ", "_")
                    if clean_school_name in output_file.name:
                        school_name = school.school_name
                        break

                # Fallback to root folder if no school match found
                if not school_name:
                    print(
                        f"WARNING: Could not determine school for {output_file.name}, uploading to root folder"
                    )
                    drive_filename = f"{timestamp}_{output_file.name}"
                    upload_to_drive_with_secrets(
                        str(output_file), drive_filename, drive_folder_id
                    )
                else:
                    drive_filename = f"{timestamp}_{output_file.name}"
                    upload_to_school_folder(
                        file_path=str(output_file),
                        filename=drive_filename,
                        school_name=school_name,
                        refresh_token=get_secret("drive-refresh-token"),
                        client_id=get_secret("drive-client-id"),
                        client_secret=get_secret("drive-client-secret"),
                        parent_folder_id=drive_folder_id,
                    )
                    print(
                        f"Uploaded {output_file.name} to {school_name} folder in Google Drive"
                    )
            except Exception as e:
                print(
                    f"WARNING: Failed to upload {output_file.name} to Google Drive: {e}"
                )


def store_completion_metadata(bucket_name: str, metadata: dict, filename: str) -> None:
    """Store completion metadata to storage"""
    upload_to_storage(bucket_name, filename, json.dumps(metadata, indent=2))


def upload_to_drive_with_secrets(file_path: str, filename: str, folder_id: str = None):
    """Upload file to Google Drive using secrets from Secret Manager"""
    try:
        refresh_token = get_secret("drive-refresh-token")
        client_id = get_secret("drive-client-id")
        client_secret = get_secret("drive-client-secret")

        return upload_to_google_drive(
            file_path=file_path,
            filename=filename,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            folder_id=folder_id,
        )
    except Exception as e:
        print(f"ERROR: Google Drive upload failed for {filename}: {str(e)}")
        raise


def upload_handler(event, context):
    """
    Cloud Function triggered by Pub/Sub (Monday scheduler)
    Submits bulk queries to AISR for immunization records
    """
    print("Upload function triggered")

    bucket_name = os.environ["DATA_BUCKET"]
    username, password = get_aisr_credentials()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Load configuration and extract URLs
        config = load_config_from_storage(bucket_name, temp_path)
        auth_url, api_url = get_aisr_urls_from_config(config)

        # Create school info list and download query files
        school_info_list = create_school_info_list(
            config, bucket_name, temp_path, include_query_files=True
        )

        school_names = [school.school_name for school in school_info_list]
        print(
            f"Loaded configuration for {len(school_info_list)} schools: {', '.join(school_names)}"
        )

        # Create and execute bulk query workflow
        action_list = create_aisr_actions_for_school_bulk_queries(school_info_list)
        query_workflow = create_aisr_workflow(login, action_list, logout)

        print("Starting AISR bulk queries")
        query_workflow(auth_url, api_url, username, password)

        # Store completion metadata
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        results_data = {
            "upload_time": datetime.now().isoformat(),
            "schools_processed": len(school_info_list),
            "status": "completed",
        }

        results_filename = f"uploads/{timestamp}_bulk_query_results.json"
        store_completion_metadata(bucket_name, results_data, results_filename)

        print(f"Upload completed: {len(school_info_list)} schools processed")
        return {"status": "success", "schools_processed": len(school_info_list)}


def download_handler(event, context):
    """
    Cloud Function triggered by Pub/Sub (Wednesday scheduler)
    Downloads vaccination records from AISR and transforms them via ETL pipeline
    """
    print("Download function triggered")

    bucket_name = os.environ["DATA_BUCKET"]
    username, password = get_aisr_credentials()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_folder = temp_path / "input"
        output_folder = temp_path / "output"
        input_folder.mkdir(exist_ok=True)
        output_folder.mkdir(exist_ok=True)

        # Load configuration and extract URLs
        config = load_config_from_storage(bucket_name, temp_path)
        auth_url, api_url = get_aisr_urls_from_config(config)

        # Create school info list (no query files needed for downloads)
        school_info_list = create_school_info_list(
            config, bucket_name, temp_path, include_query_files=False
        )

        school_names = [school.school_name for school in school_info_list]
        print(
            f"Loaded configuration for {len(school_info_list)} schools: {', '.join(school_names)}"
        )

        # Create and execute download workflow
        download_actions = create_aisr_download_actions(
            school_info_list=school_info_list, output_folder=input_folder
        )
        download_workflow = create_aisr_workflow(
            login=login, aisr_function_list=download_actions, logout=logout
        )

        print("Starting AISR vaccination record download")
        download_workflow(auth_url, api_url, username, password)

        # Run ETL transformation on downloaded files
        etl_pipeline = create_file_to_file_etl_pipeline(
            extract=read_from_aisr_csv,
            transform=transform_data_from_aisr_to_infinite_campus,
            load=write_to_infinite_campus_csv,
        )

        print("Starting ETL transformation")
        run_etl_on_folder(
            input_folder=input_folder,
            output_folder=output_folder,
            etl_fn=etl_pipeline,
        )

        # Upload transformed files to destinations
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_files = list(output_folder.glob("*.csv"))

        if output_files:
            print(
                f"Uploading {len(output_files)} transformed files to storage and Google Drive"
            )
            upload_files_to_destinations(
                output_files, bucket_name, timestamp, school_info_list
            )
            print("File uploads completed successfully")
        else:
            print("WARNING: No output files generated from ETL process")

        # Store completion metadata
        metadata = {
            "download_time": datetime.now().isoformat(),
            "schools_processed": len(school_info_list),
            "files_transformed": len(output_files),
            "status": "completed",
        }
        metadata_filename = f"downloads/{timestamp}_download_metadata.json"
        store_completion_metadata(bucket_name, metadata, metadata_filename)

        print(f"Download and ETL completed: {len(output_files)} files processed")
        return {
            "status": "success",
            "schools_processed": len(school_info_list),
            "files_transformed": len(output_files),
        }
