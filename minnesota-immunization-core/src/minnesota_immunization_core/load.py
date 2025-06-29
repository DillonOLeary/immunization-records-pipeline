"""
Functions for loading data
"""

from collections.abc import Callable
from pathlib import Path

import pandas as pd


def default_filename_generator(input_file_name: str) -> str:
    """Generate a transformed filename by adding a 'transformed_' prefix."""
    input_file_path = Path(input_file_name)

    # Simply add 'transformed_' prefix to the original filename
    return f"transformed_{input_file_path.name}"


def write_to_infinite_campus_csv(
    df: pd.DataFrame,
    output_folder: Path,
    input_file_name: str,
    filename_generator: Callable = default_filename_generator,
) -> None:
    """
    Write a DataFrame to a CSV file formatted for Infinite Campus with a unique
    filename.
    """
    output_filename = filename_generator(input_file_name)
    output_file = output_folder / output_filename
    df.to_csv(output_file, index=False, sep=",", header=False)
