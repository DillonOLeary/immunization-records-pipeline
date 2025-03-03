"""
Command-line interface module for the Minnesota Immunization Data Pipeline.

This module defines the CLI structure, argument parsing, and command handlers.
"""

import argparse
import getpass
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict

from data_pipeline.aisr.actions import SchoolQueryInformation
from data_pipeline.aisr.authenticate import AuthenticationError, login, logout
from data_pipeline.etl_workflow import run_etl_on_folder
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.metadata_generator import run_etl_with_metadata_generation
from data_pipeline.pipeline_factory import (
    create_aisr_actions_for_school_bulk_queries,
    create_aisr_workflow,
    create_file_to_file_etl_pipeline,
)
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """
    Create the argument parser with all subcommands.

    Returns:
        argparse.ArgumentParser: The configured argument parser
    """
    parser = argparse.ArgumentParser(
        description="Minnesota Immunization Data Pipeline for school districts."
    )

    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to the configuration file",
    )

    subparsers = parser.add_subparsers(
        dest="command", help="Command to execute", required=True
    )

    subparsers.add_parser(
        "transform",
        help="Transform immunization data from AISR format to Infinite Campus format",
    )

    bulk_query_parser = subparsers.add_parser(
        "bulk-query", help="Submit a bulk query to AISR for immunization records"
    )
    bulk_query_parser.add_argument(
        "--username",
        type=str,
        required=True,
        help="AISR username",
    )

    get_vax_parser = subparsers.add_parser(
        "get-vaccinations", help="Download vaccination records from AISR"
    )
    get_vax_parser.add_argument(
        "--username",
        type=str,
        required=True,
        help="AISR username",
    )

    return parser


def load_config(config_path: Path) -> Dict:
    """
    Load configuration from a JSON file.

    Example config:
    {
        "paths": {
            "input_folder": "/path/to/input",
            "output_folder": "/path/to/output",
            "logs_folder": "/path/to/logs",
            "bulk_query_folder": "/path/to/bulk_query"
        },
        "api": {
            "auth_base_url": "https://authenticator4.web.health.state.mn.us",
            "aisr_api_base_url": "https://aisr-api.web.health.state.mn.us"
        },
        "schools": [
            {
                "name": "Friendly Hills",
                "id": "1234",
                "classification": "N",
                "email": "test@example.com"
            }
        ]
    }

    Args:
        config_path: Path to the configuration file

    Returns:
        dict: Configuration dictionary

    Raises:
        FileNotFoundError: If the config file doesn't exist
        json.JSONDecodeError: If the config file contains invalid JSON
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "paths" not in config:
        raise ValueError("Config file must contain a 'paths' section")

    # Convert string paths to Path objects
    paths = config["paths"]
    for key in ["input_folder", "output_folder", "logs_folder", "bulk_query_folder"]:
        if key in paths and isinstance(paths[key], str):
            paths[key] = Path(paths[key])

    return config


def get_password_from_env_or_prompt() -> str:
    """
    Get password from environment variable or prompt.

    Returns:
        str: The password
    """

    # Check if password is in environment
    password = os.environ.get("AISR_PASSWORD")
    if password:
        return password

    # Prompt for password
    return getpass.getpass("Enter your AISR password: ")


def validate_api_config(config: Dict) -> tuple[str, str]:
    """
    Validate API configuration and return auth and API URLs.

    Args:
        config: Configuration dictionary

    Returns:
        Tuple of (auth_url, api_url)

    Raises:
        ValueError: If API URLs are missing
    """
    api_config = config.get("api", {})
    auth_url = api_config.get("auth_base_url")
    api_url = api_config.get("aisr_api_base_url")

    if not auth_url or not api_url:
        raise ValueError("Missing API URLs in configuration")

    return auth_url, api_url


def validate_input_folder(config: Dict) -> Path:
    """
    Validate the input folder (AISR downloads folder) exists.

    The input_folder is where AISR downloaded files are stored before processing.

    Args:
        config: Configuration dictionary

    Returns:
        Path to input folder (AISR downloads)

    Raises:
        ValueError: If input folder is missing or doesn't exist
    """
    input_folder = config["paths"].get("input_folder")
    if not input_folder or not Path(input_folder).exists():
        raise ValueError(
            "AISR downloads folder (input_folder) doesn't exist or is not configured"
        )

    return Path(input_folder)


def validate_bulk_query_folder(config: Dict) -> Path:
    """
    Validate the bulk query folder exists.

    The bulk_query_folder is where query files for AISR bulk queries are stored.

    Args:
        config: Configuration dictionary

    Returns:
        Path to bulk query folder

    Raises:
        ValueError: If bulk query folder is missing or doesn't exist
    """
    bulk_query_folder = config["paths"].get("bulk_query_folder")
    if not bulk_query_folder or not Path(bulk_query_folder).exists():
        raise ValueError(
            "Bulk query folder (bulk_query_folder) doesn't exist or is not configured"
        )

    return Path(bulk_query_folder)


def get_school_query_information(
    schools: list, query_folder: Path
) -> list[SchoolQueryInformation]:
    """
    Create SchoolQueryInformation objects for each school.

    Args:
        schools: List of school configurations
        query_folder: Path to bulk query folder containing query files

    Returns:
        List of SchoolQueryInformation objects

    Raises:
        ValueError: If no valid schools are found
    """
    if not schools:
        raise ValueError("No schools found in configuration")

    logger.info("Found %d school(s) in configuration", len(schools))

    school_info_list = []
    for school in schools:
        school_name = school.get("name", "Unknown")
        school_id = school.get("id")
        classification = school.get("classification")
        email = school.get("email")
        query_file_str = school.get("bulk_query_file")

        if not all([school_id, classification, email, query_file_str]):
            logger.error("School %s is missing required information", school_name)
            continue

        # Convert string path to Path object
        query_file = Path(query_file_str)
        if not query_file.exists():
            logger.error(
                "Query file not found for school %s: %s", school_name, query_file
            )
            raise ValueError(
                f"No query file for {school_name} in bulk query folder"
            )

        logger.info("Processing request for %s", school_name)

        school_info = SchoolQueryInformation(
            school_name=school_name,
            classification=classification,
            school_id=school_id,
            email_contact=email,
            query_file_path=query_file_str,
        )
        school_info_list.append(school_info)

    if not school_info_list:
        raise ValueError("No valid schools to process")

    return school_info_list


def try_query_workflow(workflow_fn, auth_url, api_url, username, password):
    """
    Executes a workflow with proper error handling.

    Args:
        workflow_fn: The workflow function to execute
        auth_url: Authentication URL
        api_url: API URL
        username: AISR username
        password: AISR password

    Raises:
        AuthenticationError: Re-raises authentication errors for CLI to handle
    """
    try:
        workflow_fn(auth_url, api_url, username, password)
    except AuthenticationError as e:
        logger.error("Authentication Failed: %s", e)


def execute_bulk_query(
    auth_url: str,
    api_url: str,
    username: str,
    password: str,
    school_info_list: list[SchoolQueryInformation],
) -> None:
    """
    Execute the bulk query workflow.

    Args:
        auth_url: Authentication URL
        api_url: API URL
        username: AISR username
        password: AISR password
        school_info_list: List of SchoolQueryInformation objects
    """
    action_list = create_aisr_actions_for_school_bulk_queries(school_info_list)
    query_workflow = create_aisr_workflow(login, action_list, logout)

    try_query_workflow(query_workflow, auth_url, api_url, username, password)

    # If we get here, the workflow completed without errors
    logger.info("Bulk query completed successfully")


def handle_bulk_query_command(args: argparse.Namespace, config: Dict) -> None:
    """
    Handle the bulk-query command to submit a query to AISR.

    Args:
        args: Command line arguments
        config: Loaded configuration
    """
    logger.info("Bulk query command started")

    # Get authentication credentials
    username = args.username
    password = get_password_from_env_or_prompt()

    # Validate configuration
    auth_url, api_url = validate_api_config(config)
    
    # Use the bulk query folder for query files
    bulk_query_folder = validate_bulk_query_folder(config)
    logger.info("Using bulk query folder: %s", bulk_query_folder)

    # Get school query information
    school_info_list = get_school_query_information(
        config.get("schools", []), bulk_query_folder
    )

    # Execute the bulk query
    execute_bulk_query(auth_url, api_url, username, password, school_info_list)

    logger.info("Bulk query command finished")


def handle_get_vaccinations_command(args: argparse.Namespace, config: Dict) -> None:
    """
    Handle the get-vaccinations command to download vaccination records.

    Args:
        args: Command line arguments
        config: Loaded configuration
    """
    raise NotImplementedError


def handle_transform_command(config: Dict) -> None:
    """
    Handle the transform command to convert data from AISR to Infinite Campus format.

    Args:
        config: Loaded configuration
    """

    logger.info("Transform command started")

    # Get paths from config
    paths = config.get("paths", {})
    input_folder = paths.get("input_folder")  # AISR downloads folder
    output_folder = paths.get("output_folder")

    if not input_folder or not output_folder:
        logger.error(
            "Missing AISR downloads folder (input_folder) or output folder in configuration"
        )
        sys.exit(1)

    # Ensure output folder exists
    output_folder.mkdir(parents=True, exist_ok=True)

    # Create metadata folder
    metadata_folder = output_folder / "metadata"
    metadata_folder.mkdir(parents=True, exist_ok=True)

    # Create the ETL pipeline with injected dependencies
    etl_pipeline = create_file_to_file_etl_pipeline(
        extract=read_from_aisr_csv,
        transform=transform_data_from_aisr_to_infinite_campus,
        load=write_to_infinite_campus_csv,
    )

    etl_pipeline_with_metadata = run_etl_with_metadata_generation(
        Path(output_folder) / "metadata"
    )(etl_pipeline)

    run_etl_on_folder(
        input_folder=input_folder,
        output_folder=output_folder,
        etl_fn=etl_pipeline_with_metadata,
    )

    logger.info("Transform command finished")
