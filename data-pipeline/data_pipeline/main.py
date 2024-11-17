"""
Inject dependencies and run pipeline
"""

import argparse
from pathlib import Path

from data_pipeline.data_flow import run_pipeline
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus


def parse_args():
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with file_in_path and file_out_path.
    """
    parser = argparse.ArgumentParser(
        description="Run the immunization data pipeline, transforming and saving data."
    )
    parser.add_argument(
        "file_in_path", type=Path, help="Path to the input CSV file (AISR data)"
    )
    parser.add_argument(
        "file_out_path", type=Path, help="Path to save the transformed CSV file"
    )
    return parser.parse_args()


if __name__ == "__main__":
    # pylint: disable=invalid-name

    # pylint: disable=line-too-long
    # poetry run python data_pipeline/main.py tests/mock_data/mock_aisr_download.csv output/mock_transformed_data.csv

    args = parse_args()

    result_message = run_pipeline(
        extract_function=lambda: read_from_aisr_csv(args.file_in_path),
        transform_function=transform_data_from_aisr_to_infinite_campus,
        load_function=lambda df: write_to_infinite_campus_csv(df, args.file_out_path),
    )

    print(result_message)
