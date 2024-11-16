"""
Functions for reading from a csv
"""

from pathlib import Path

import pandas as pd


def read_from_aisr_csv(file_path: Path) -> pd.DataFrame:
    """
    Reads an AISR-formatted CSV file into a pandas DataFrame.

    This function expects the CSV to have a specific format that is typically used
    for AISR data, and it will load it into a pandas DataFrame for further processing.

    Args:
        file_path (Path): The path to the CSV file to be read.

    Returns:
        pd.DataFrame: A pandas DataFrame containing the data from the CSV file.

    Raises:
        FileNotFoundError: If the file at the specified path does not exist.
        ValueError: If the file is not formatted correctly or cannot be read.
    """
    df = pd.read_csv(file_path, sep="|")
    # TODO this does not catch errors and can crash the program
    return df
