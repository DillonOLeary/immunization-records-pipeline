"""Command-line interface: argument parsing and command handlers.

Handlers wire the AISR client and the domain together directly; there are no
intermediate workflow factories. Each command reads config, opens an AISR
session where needed, and performs its steps in plain loops.
"""

import argparse
import getpass
import json
import logging
import os
import sys
from pathlib import Path

from mn_immunization.domain.ic_format import IcFormatError, render_csv
from mn_immunization.runtime.files import (
    generate_vaccination_record_filename,
    transformed_filename,
)
from mn_immunization.runtime.metadata_generator import (
    run_etl_with_metadata_generation,
)
from mn_immunization.sources.aisr.actions import (
    AISRActionFailedError,
    SchoolQueryInformation,
)
from mn_immunization.sources.aisr.authenticate import AuthenticationError
from mn_immunization.sources.aisr.client import aisr_session
from mn_immunization.sources.aisr.parsing import AisrParseError, parse_aisr_csv

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
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

    status_parser = subparsers.add_parser(
        "status", help="Show recent pipeline runs from the ledger"
    )
    status_parser.add_argument(
        "--bucket",
        type=str,
        required=True,
        help="GCS bucket holding the ledger",
    )
    status_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of runs to show (default 10)",
    )

    return parser


def load_config(config_path: Path) -> dict:
    """Load configuration from a JSON file.

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
                "email": "test@example.com",
                "bulk_query_file": "/path/to/query_files/Friendly Hills/query.csv"
            }
        ]
    }
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    if "paths" not in config:
        raise ValueError("Config file must contain a 'paths' section")

    paths = config["paths"]
    for key in ["input_folder", "output_folder", "logs_folder"]:
        if key in paths and isinstance(paths[key], str):
            paths[key] = Path(paths[key])

    return config


def get_password_from_env_or_prompt() -> str:
    """Get the AISR password from AISR_PASSWORD or an interactive prompt."""
    password = os.environ.get("AISR_PASSWORD")
    if password:
        return password
    return getpass.getpass("Enter your AISR password: ")


def validate_api_config(config: dict) -> tuple[str, str]:
    """Return (auth_url, api_url) or raise if either is missing."""
    api_config = config.get("api", {})
    auth_url = api_config.get("auth_base_url")
    api_url = api_config.get("aisr_api_base_url")

    if not auth_url or not api_url:
        raise ValueError("Missing API URLs in configuration")

    return auth_url, api_url


def validate_input_folder(config: dict) -> Path:
    """Return the AISR downloads folder (input_folder), which must exist."""
    input_folder = config["paths"].get("input_folder")
    if not input_folder or not Path(input_folder).exists():
        raise ValueError(
            "AISR downloads folder (input_folder) doesn't exist or is not configured"
        )

    return Path(input_folder)


def get_school_query_information(schools: list) -> list[SchoolQueryInformation]:
    """Build SchoolQueryInformation for each configured school."""
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

        query_file = Path(query_file_str)
        if not query_file.exists():
            logger.error(
                "Query file not found for school %s: %s", school_name, query_file
            )
            raise ValueError(f"No query file found at {query_file} for {school_name}")

        logger.info("Processing request for %s", school_name)

        school_info_list.append(
            SchoolQueryInformation(
                school_name=school_name,
                classification=classification,
                school_id=school_id,
                email_contact=email,
                query_file_path=query_file_str,
            )
        )

    if not school_info_list:
        raise ValueError("No valid schools to process")

    return school_info_list


def transform_file(input_file: Path, output_folder: Path) -> str:
    """Transform one AISR results file into an IC-format file."""
    records = parse_aisr_csv(input_file.read_text(encoding="utf-8"))
    output_file = output_folder / transformed_filename(input_file.name)
    output_file.write_text(render_csv(records), encoding="utf-8")
    return "Data pipeline executed successfully"


def handle_transform_command(config: dict) -> None:
    """Transform every AISR file in the input folder."""
    logger.info("Transform command started")

    paths = config.get("paths", {})
    input_folder = paths.get("input_folder")
    output_folder = paths.get("output_folder")

    if not input_folder or not output_folder:
        logger.error(
            "Missing AISR downloads folder(input_folder) or output folder in configuration"  # noqa: E501
        )
        sys.exit(1)

    output_folder.mkdir(parents=True, exist_ok=True)
    metadata_folder = Path(output_folder) / "metadata"
    metadata_folder.mkdir(parents=True, exist_ok=True)

    transform_with_metadata = run_etl_with_metadata_generation(metadata_folder)(
        transform_file
    )

    for input_file in Path(input_folder).glob("*.csv"):
        logger.info("Processing file: %s", input_file)
        try:
            transform_with_metadata(input_file, Path(output_folder))
        except (AisrParseError, IcFormatError, OSError) as error:
            # Error class only: parse messages can quote a field value (PHI).
            logger.error(
                "Transform failed for file %s: %s",
                input_file.name,
                type(error).__name__,
            )

    logger.info("Transform command finished")


def handle_bulk_query_command(args: argparse.Namespace, config: dict) -> None:
    """Submit each school's roster query to AISR."""
    logger.info("Bulk query command started")

    username = args.username
    password = get_password_from_env_or_prompt()
    auth_url, api_url = validate_api_config(config)
    school_info_list = get_school_query_information(config.get("schools", []))

    failures = 0
    try:
        with aisr_session(auth_url, api_url, username, password) as client:
            for school in school_info_list:
                try:
                    client.submit_roster_query(school)
                    logger.info("Submitted bulk query for %s", school.school_name)
                except AISRActionFailedError:
                    failures += 1
                    logger.error(
                        "Bulk query failed for %s", school.school_name, exc_info=True
                    )
    except AuthenticationError as error:
        logger.error("Authentication failed: %s", error)
        sys.exit(1)

    if failures:
        logger.error("Bulk query finished with %d failure(s)", failures)
        sys.exit(1)
    logger.info("Bulk query completed successfully")


def handle_get_vaccinations_command(args: argparse.Namespace, config: dict) -> None:
    """Download the latest vaccination records for each school."""
    logger.info("Starting download of vaccination records")

    username = args.username
    password = get_password_from_env_or_prompt()
    auth_url, api_url = validate_api_config(config)

    paths = config.get("paths", {})
    aisr_downloads_folder = paths.get(
        "aisr_downloads_folder", paths.get("input_folder")
    )
    if not aisr_downloads_folder:
        logger.error("Missing AISR downloads folder in configuration")
        sys.exit(1)

    aisr_downloads_folder = Path(aisr_downloads_folder)
    aisr_downloads_folder.mkdir(parents=True, exist_ok=True)

    school_info_list = get_school_query_information(config.get("schools", []))

    failures = 0
    try:
        with aisr_session(auth_url, api_url, username, password) as client:
            for school in school_info_list:
                output_path = aisr_downloads_folder / (
                    generate_vaccination_record_filename(school.school_name)
                )
                try:
                    client.download_latest_records(school.school_id, output_path)
                    logger.info(
                        "Downloaded records for %s to %s",
                        school.school_name,
                        output_path,
                    )
                except AISRActionFailedError:
                    failures += 1
                    logger.error(
                        "Download failed for %s", school.school_name, exc_info=True
                    )
    except AuthenticationError as error:
        logger.error("Authentication failed: %s", error)
        sys.exit(1)

    if failures:
        logger.error("Downloads finished with %d failure(s)", failures)
        sys.exit(1)
    logger.info("Vaccination records downloaded successfully")


def handle_status_command(args: argparse.Namespace) -> None:
    """Print recent runs and their terminal outcomes from the ledger."""
    from datetime import datetime

    from mn_immunization.ledger.events import TERMINAL_TYPES
    from mn_immunization.ledger.gcs_ledger import read_recent_runs
    from mn_immunization.runtime.cloud.cloud_storage import get_storage_client

    now = datetime.now()
    previous = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    months = ((now.year, now.month), previous)

    bucket = get_storage_client().bucket(args.bucket)
    runs = read_recent_runs(bucket, months, limit=args.limit)

    if not runs:
        print("No runs found in the ledger for the last two months.")
        return

    for run in runs:
        first, last = run["events"][0], run["events"][-1]
        if last["type"] in TERMINAL_TYPES:
            outcome = last["type"]
            detail = ", ".join(f"{k}={v}" for k, v in last["data"].items())
        else:
            outcome = "NO TERMINAL EVENT"
            detail = f"last event: {last['type']}"
        print(f"{first['at']}  {run['run_id']}")
        print(f"    {outcome}  {detail}")
