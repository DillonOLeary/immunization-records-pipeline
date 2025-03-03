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

from data_pipeline.etl_workflow import run_etl_on_folder
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.metadata_generator import run_etl_with_metadata_generation
from data_pipeline.pipeline_factory import create_file_to_file_etl_pipeline
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus


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
            "logs_folder": "/path/to/logs"
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
    for key in ["input_folder", "output_folder", "logs_folder"]:
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


def handle_bulk_query_command(args: argparse.Namespace, config: Dict) -> None:
    """
    Handle the bulk-query command to submit a query to AISR.

    Args:
        args: Command line arguments
        config: Loaded configuration
    """
    # TODO
    raise NotImplementedError
    # logger = logging.getLogger(__name__)
    # logger.info("Bulk query command started")

    # try:
    #     username = args.username

    #     # Get password
    #     password = get_password_from_env_or_prompt()

    #     # Get API configuration
    #     api_config = config.get("api", {})
    #     auth_url = api_config.get("auth_base_url")
    #     api_url = api_config.get("aisr_api_base_url")

    #     if not auth_url or not api_url:
    #         logger.error("Missing API URLs in configuration")
    #         print("Error: Missing API URLs in configuration", file=sys.stderr)
    #         sys.exit(1)

    #     # Log which schools will be queried
    #     schools = config.get("schools", [])
    #     if not schools:
    #         logger.error("No schools found in configuration")
    #         print("Error: No schools found in configuration", file=sys.stderr)
    #         sys.exit(1)

    #     logger.info(f"Found {len(schools)} school(s) in configuration")

    # TODO: Implement the actual query functionality
    #     for school in schools:
    #         school_name = school.get("name", "Unknown")
    #         print(f"Processing request for {school_name}")
    #         logger.info(f"Processing request for {school_name}")

    #     logger.info("Bulk query command finished")

    # except Exception as e:
    #     logger.exception(f"Unexpected error: {e}")
    #     print(f"Error: {e}", file=sys.stderr)
    #     sys.exit(1)


def handle_get_vaccinations_command(args: argparse.Namespace, config: Dict) -> None:
    """
    Handle the get-vaccinations command to download vaccination records.

    Args:
        args: Command line arguments
        config: Loaded configuration
    """
    raise NotImplementedError
    # logger = logging.getLogger(__name__)
    # logger.info("Get vaccinations command started")

    # try:
    #     username = args.username

    #     # Get password
    #     password = get_password_from_env_or_prompt()

    #     # Get API configuration
    #     api_config = config.get("api", {})
    #     auth_url = api_config.get("auth_base_url")
    #     api_url = api_config.get("aisr_api_base_url")

    #     if not auth_url or not api_url:
    #         logger.error("Missing API URLs in configuration")
    #         print("Error: Missing API URLs in configuration", file=sys.stderr)
    #         sys.exit(1)

    #     # Ensure output folder exists
    #     output_folder = config["paths"].get("output_folder")
    #     if not output_folder:
    #         logger.error("Missing output folder in configuration")
    #         print("Error: Missing output folder in configuration", file=sys.stderr)
    #         sys.exit(1)

    #     output_folder.mkdir(parents=True, exist_ok=True)

    #     # Log which schools will be queried
    #     schools = config.get("schools", [])
    #     if not schools:
    #         logger.error("No schools found in configuration")
    #         print("Error: No schools found in configuration", file=sys.stderr)
    #         sys.exit(1)

    #     logger.info(f"Found {len(schools)} school(s) in configuration")

    #     # TODO: Implement the actual download functionality
    #     for school in schools:
    #         school_name = school.get("name", "Unknown")
    #         print(f"Downloading vaccination records for {school_name}")
    #         logger.info(f"Downloading vaccination records for {school_name}")

    #     logger.info("Get vaccinations command finished")

    # except Exception as e:
    #     logger.exception(f"Unexpected error: {e}")
    #     print(f"Error: {e}", file=sys.stderr)
    #     sys.exit(1)


# def run(config):
#     """
#     Gather CL args, set up the project and run the ETL
#     """
#     logger = logging.getLogger(__name__)

#     logger.info("Program started")

#     # Create the ETL pipeline with injected dependencies
#     etl_pipeline = create_file_to_file_etl_pipeline(
#         extract=read_from_aisr_csv,
#         transform=transform_data_from_aisr_to_infinite_campus,
#         load=write_to_infinite_campus_csv,
#     )

#     etl_pipeline_with_metadata = run_etl_with_metadata_generation(
#         Path(args.output_folder) / "metadata"
#     )(etl_pipeline)

#     run_etl_on_folder(
#         input_folder=args.input_folder,
#         output_folder=args.output_folder,
#         etl_fn=etl_pipeline_with_metadata,
#     )

#     logger.info("Program finished")


def handle_transform_command(config: Dict) -> None:
    """
    Handle the transform command to convert data from AISR to Infinite Campus format.

    Args:
        config: Loaded configuration
    """

    logger = logging.getLogger(__name__)
    logger.info("Transform command started")

    # Get paths from config
    paths = config.get("paths", {})
    input_folder = paths.get("input_folder")
    output_folder = paths.get("output_folder")

    if not input_folder or not output_folder:
        logger.error("Missing input or output folder in configuration")
        print("Error: Missing input or output folder in configuration", file=sys.stderr)
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
