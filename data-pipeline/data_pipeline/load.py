"""
Functions for loading data
"""

from pathlib import Path

import pandas as pd


def write_to_infinite_campus_csv(df: pd.DataFrame, output_file: Path) -> None:
    """
    Write a DataFrame to a CSV file formatted for Infinite Campus.

    Args:
        df (pd.DataFrame): The DataFrame to write.
        output_file (Path): The file path where the CSV should be saved.

    Returns:
        None
    """

    # Write the DataFrame to a CSV file using a comma as the separator
    df.to_csv(output_file, index=False, sep=",")
