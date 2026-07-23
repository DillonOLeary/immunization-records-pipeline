"""Command-line interface: argument parsing and command handlers.

Handlers wire the AISR client and the domain together directly; there are no
intermediate workflow factories. Each command reads config, opens an AISR
session where needed, and performs its steps in plain loops.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from mn_immunization.domain.ic_format import IcFormatError, render_csv
from mn_immunization.pipeline.files import (
    transformed_filename,
)
from mn_immunization.runtime.metadata_generator import (
    run_etl_with_metadata_generation,
)
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


def handle_status_command(args: argparse.Namespace) -> None:
    """Print recent runs and their terminal outcomes from the ledger."""
    from datetime import datetime

    from mn_immunization.gcp.storage import get_storage_client
    from mn_immunization.ledger.events import TERMINAL_TYPES
    from mn_immunization.ledger.gcs_ledger import read_recent_runs

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
