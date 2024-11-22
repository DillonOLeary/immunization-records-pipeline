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
    Run the etl data pipeline.

    Args:
        extract (Callable[[], pd.DataFrame]):
            Function that extracts data and returns a DataFrame.
        transform (Callable[[pd.DataFrame], pd.DataFrame]):
            Function that takes a DataFrame as input and returns a transformed DataFrame.
        load (Callable[[pd.DataFrame], None]):
            Function that loads the transformed dataframe.
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

    Args:
        input_folder (Path): The folder containing the input CSV files.
        output_folder (Path): The folder to save the transformed files.
        etl_fn (Callable[[Path, Path], str]): The ETL function to process individual files.
    """
    # Ensure the output folder exists
    output_folder.mkdir(parents=True, exist_ok=True)

    # Iterate over each CSV file in the input folder and run the ETL pipeline
    for input_file in input_folder.glob("*.csv"):
        result_message = etl_fn(input_file, output_folder)
        print(f"Processed {input_file.name}: {result_message}")

    print("Pipeline completed successfully.")
