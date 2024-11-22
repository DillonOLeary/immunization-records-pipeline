"""
Inject dependencies and run pipeline
"""

import argparse
from pathlib import Path

from data_pipeline.etl_workflow import run_etl_on_folder
from data_pipeline.execution_logger import log_etl_run
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.pipeline_factory import create_file_to_file_etl_pipeline
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus


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
        "--log_folder",
        type=Path,
        required=True,
        help="Path to the folder where the log of ETL runs will be saved",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Create the ETL pipeline with injected dependencies
    etl_pipeline = create_file_to_file_etl_pipeline(
        extract=read_from_aisr_csv,
        transform=transform_data_from_aisr_to_infinite_campus,
        load=write_to_infinite_campus_csv,
    )

    # Apply the logging decorator to track ETL runs
    etl_pipeline_with_logging = log_etl_run(args.log_folder)(etl_pipeline)

    # Run the ETL pipeline on all files in the input folder
    run_etl_on_folder(
        input_folder=args.input_folder,
        output_folder=args.output_folder,
        etl_fn=etl_pipeline_with_logging,
    )
