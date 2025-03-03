"""
Entry point for the Minnesota Immunization Data Pipeline
"""

import logging
import logging.config
import sys
from pathlib import Path

from data_pipeline.cli import (
    create_parser,
    handle_bulk_query_command,
    handle_get_vaccinations_command,
    handle_transform_command,
    load_config,
)

CONFIG_DIR = Path("config")


def setup_logging(env: str, log_dir: Path = Path("logs")):
    """
    Set up logging configuration.
    """
    log_configs = {"dev": "logging.dev.ini", "prod": "logging.prod.ini"}
    config_path = CONFIG_DIR / log_configs.get(env, "logging.dev.ini")

    # Create log directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.config.fileConfig(
        config_path,
        disable_existing_loggers=False,
        defaults={"logfilename": str(log_dir / "app.log")},
    )


def run():
    """
    Parse args, set up the project and run the appropriate command
    """
    parser = create_parser()
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    logs_folder = config.get("paths", {}).get("logs_folder", Path("logs"))
    setup_logging("dev", log_dir=logs_folder)

    if args.command == "transform":
        handle_transform_command(config)
    elif args.command == "bulk-query":
        handle_bulk_query_command(args, config)
    elif args.command == "get-vaccinations":
        handle_get_vaccinations_command(args, config)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    run()
