"""
Functions for extracting data
"""

from pathlib import Path

import pandas as pd

# pylint: disable=fixme


def read_from_aisr_csv(file_path: Path) -> pd.DataFrame:
    """
    Reads an AISR-formatted CSV file into a pandas DataFrame.
    """
    df = pd.read_csv(file_path, sep="|")
    # TODO this does not catch errors and can crash the program
    return df
