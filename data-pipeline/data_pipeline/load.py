"""
Functions for loading data
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pandas as pd


def default_filename_generator(input_file_name: str) -> str:
    """Generate a unique filename by appending a timestamp."""
    input_file_path = Path(input_file_name)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]  # Shortened UUID for brevity

    # Use the stem attribute to get the filename without extension
    return f"transformed_{input_file_path.stem}_{timestamp}_{unique_id}.csv"


def write_to_infinite_campus_csv(
    df: pd.DataFrame,
    output_folder: Path,
    input_file_name: Path,
    filename_generator: Callable = default_filename_generator,
) -> None:
    """
    Write a DataFrame to a CSV file formatted for Infinite Campus with a unique filename.
    """
    output_filename = filename_generator(input_file_name)
    output_file = output_folder / output_filename
    df.to_csv(output_file, index=False, sep=",", header=False)
