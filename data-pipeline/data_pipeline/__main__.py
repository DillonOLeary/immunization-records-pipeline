"""
Inject dependencies and run pipeline
"""

import argparse
from collections.abc import Callable
from pathlib import Path

from data_pipeline.etl_pipeline import run_etl, run_etl_on_folder
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.manifest_generator import log_etl_run
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
        "--manifest_folder",
        type=Path,
        required=True,
        help="Path to the folder where the manifest of ETL runs will be saved",
    )
    return parser.parse_args()


def create_etl_pipeline(extract, transform, load) -> Callable[[Path, Path], str]:
    """
    Creates an ETL pipeline by injecting the extract, transform, and load functions.

    Args:
        extract (Callable[[], pd.DataFrame]): Function to extract data from input.
        transform (Callable[[pd.DataFrame], pd.DataFrame]):
            Function to transform the extracted data.
        load (Callable[[pd.DataFrame], None]):
            Function to load the transformed data to a destination.

    Returns:
        Callable[[Path, Path], str]: A function that runs the full ETL pipeline on a file.
    """

    def etl_fn(input_file: Path, output_folder: Path) -> str:
        """
        Runs the ETL pipeline on a single input file.

        Args:
            input_file (Path): The input file to process.
            output_folder (Path): The folder where output will be saved.

        Returns:
            str: A success message if the ETL pipeline completes successfully.
        """
        return run_etl(
            extract=lambda: extract(input_file),
            transform=transform,
            load=lambda df: load(df, output_folder, input_file.name),
        )

    return etl_fn


if __name__ == "__main__":
    args = parse_args()

    # Create the ETL pipeline with injected dependencies
    etl_pipeline = create_etl_pipeline(
        extract=read_from_aisr_csv,
        transform=transform_data_from_aisr_to_infinite_campus,
        load=write_to_infinite_campus_csv,
    )

    # Apply the logging decorator to track ETL runs
    etl_pipeline_with_logging = log_etl_run(args.manifest_folder)(etl_pipeline)

    # Run the ETL pipeline on all files in the input folder
    run_etl_on_folder(
        input_folder=args.input_folder,
        output_folder=args.output_folder,
        etl_fn=etl_pipeline_with_logging,
    )
