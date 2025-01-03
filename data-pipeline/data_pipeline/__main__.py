"""
Inject dependencies and run pipeline
"""

import argparse
import datetime
import logging
import logging.config
import os
from pathlib import Path

from data_pipeline.etl_workflow import run_etl_on_folder
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.metadata_generator import run_etl_with_metadata_generation
from data_pipeline.pipeline_factory import create_file_to_file_etl_pipeline
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus

CONFIG_DIR = Path("config")


def parse_args():
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with input_folder and output_folder.
    """
    parser = argparse.ArgumentParser(
        description="Run the immunization data pipeline, transforming and saving data."
    )
    parser.add_argument(
        "--input_folder",
        type=Path,
        required=True,
        help="Path to the input folder containing CSV files (AISR data)",
    )
    parser.add_argument(
        "--output_folder",
        type=Path,
        required=True,
        help="Path to the folder where transformed files will be saved",
    )
    parser.add_argument(
        "--logs_folder",
        type=Path,
        required=False,
        default="logs",
        help="Path to the folder where log files will be saved",
    )
    return parser.parse_args()


def setup_logging(env: str, log_dir: Path = Path("logs")):
    """
    Set up logging configuration.
    """
    log_configs = {"dev": "logging.dev.ini", "prod": "logging.prod.ini"}
    config_path = CONFIG_DIR / log_configs.get(env, "logging.dev.ini")

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H:%M:%S")

    logging.config.fileConfig(
        config_path,
        disable_existing_loggers=False,
        defaults={"logfilename": log_dir / f"{timestamp}.log"},
    )


def run():
    """
    Gather CL args, set up the project and run the ETL
    """
    args = parse_args()

    setup_logging("dev", log_dir=args.logs_folder)
    logger = logging.getLogger(__name__)

    logger.info("Program started")

    # Create the ETL pipeline with injected dependencies
    etl_pipeline = create_file_to_file_etl_pipeline(
        extract=read_from_aisr_csv,
        transform=transform_data_from_aisr_to_infinite_campus,
        load=write_to_infinite_campus_csv,
    )

    etl_pipeline_with_metadata = run_etl_with_metadata_generation(
        Path(args.output_folder) / "metadata"
    )(etl_pipeline)

    run_etl_on_folder(
        input_folder=args.input_folder,
        output_folder=args.output_folder,
        etl_fn=etl_pipeline_with_metadata,
    )

    logger.info("Program finished")


if __name__ == "__main__":
    run()
