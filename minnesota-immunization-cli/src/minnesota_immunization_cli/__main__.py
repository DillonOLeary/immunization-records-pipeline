import logging
import logging.config
import sys
from pathlib import Path

from minnesota_immunization_cli.cli import (
    create_parser,
    handle_bulk_query_command,
    handle_get_vaccinations_command,
    handle_transform_command,
    load_config,
)

CONFIG_DIR = Path("config")


def setup_logging(env: str, log_dir: Path = Path("logs")):
    """
    Set up logging configuration based on environment.
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


def parse_arguments():
    """Parse and return command-line arguments."""
    parser = create_parser()
    return parser.parse_args()


def load_application_config(config_path: str):
    """Load the configuration from the provided path."""
    try:
        return load_config(config_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def execute_command(args, config):
    """Execute the command based on parsed arguments."""
    if args.command == "transform":
        handle_transform_command(config)
    elif args.command == "bulk-query":
        handle_bulk_query_command(args, config)
    elif args.command == "get-vaccinations":
        handle_get_vaccinations_command(args, config)
    else:
        print("Unknown command:", args.command)
        sys.exit(1)


def run():
    """
    Main entry point: Parse args, load config, and run the appropriate command.
    """
    args = parse_arguments()
    config = load_application_config(args.config)

    logs_folder = config.get("paths", {}).get("logs_folder", Path("logs"))
    setup_logging("dev", log_dir=logs_folder)

    logger = logging.getLogger(__name__)

    try:
        execute_command(args, config)
    except Exception as e:
        logger.error("Program failed with error: %s", e)
        sys.exit(1)
