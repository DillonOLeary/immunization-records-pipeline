"""
This file runs the immunization data pipeline.
"""

from collections.abc import Callable
from pathlib import Path

import pandas as pd


def run_etl(
    extract: Callable[[], pd.DataFrame],
    transform: Callable[[pd.DataFrame], pd.DataFrame],
    load: Callable[[pd.DataFrame], None],
) -> str:
    """
    Run the etl data pipeline with functions passed in.

    Returns:
        str: A message stating the run successed or failed
    """
    df_in = extract()
    transformed_df = transform(df_in)
    load(transformed_df)
    return "Data pipeline executed successfully"


def run_etl_on_folder(
    input_folder: Path, output_folder: Path, etl_fn: Callable[[Path, Path], str]
):
    """
    Runs the ETL pipeline for all CSV files in the input folder
    and saves the results to the output folder.
    """
    # Ensure the output folder exists
    output_folder.mkdir(parents=True, exist_ok=True)

    # Iterate over each CSV file in the input folder and run the ETL pipeline
    for input_file in input_folder.glob("*.csv"):
        result_message = etl_fn(input_file, output_folder)
        print(f"Processed {input_file.name}: {result_message}")

    print("Successfully ran etl for all files in input folder.")
