"""
Functions for loading data
"""

from pathlib import Path

import pandas as pd


def write_to_infinite_campus_csv(df: pd.DataFrame, output_folder: Path, input_file_name: str) -> None:
    """
    Write a DataFrame to a CSV file formatted for Infinite Campus.

    Args:
        df (pd.DataFrame): The DataFrame to write.
        output_folder (Path): The folder where the CSV should be saved.
        input_file_name (str): The name of the input file (used for naming the output file).

    Returns:
        None
    """
    output_file = output_folder / f"transformed_{input_file_name}"
    df.to_csv(output_file, index=False, sep=",")
