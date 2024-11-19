"""
Inject dependencies and run pipeline
"""

import argparse
from pathlib import Path

from data_pipeline.etl_pipeline import run_etl
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
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
    return parser.parse_args()


if __name__ == "__main__":
    # pylint: disable=invalid-name
    # pylint: disable=cell-var-from-loop
    # Lazy evaluation is fine for this loop because the function
    # runs immediately

    args = parse_args()

    # Ensure the output folder exists
    args.output_folder.mkdir(parents=True, exist_ok=True)

    for input_file in args.input_folder.glob("*.csv"):
        result_message = run_etl(
            extract=lambda: read_from_aisr_csv(input_file),
            transform=transform_data_from_aisr_to_infinite_campus,
            load=lambda df: write_to_infinite_campus_csv(
                df, args.output_folder, input_file.name
            ),
        )

    print("Pipeline completed successfully.")
