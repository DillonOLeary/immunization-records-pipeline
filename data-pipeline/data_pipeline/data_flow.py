"""
This file runs the immunization data pipeline.
"""

from collections.abc import Callable

import pandas as pd

# pylint: disable=fixme


def run_pipeline(
    extract_function: Callable[[], pd.DataFrame],
    transform_function: Callable[[pd.DataFrame], pd.DataFrame],
    load_function: Callable[[pd.DataFrame], None],
) -> str:
    """
    Run the data pipeline.

    Args:
        extract_function (Callable[[], pd.DataFrame]):
            Function that extracts data and returns a DataFrame.
        transform_function (Callable[[pd.DataFrame], pd.DataFrame]):
            Function that takes a DataFrame as input and returns a transformed DataFrame.
    """
    df_in = extract_function()
    transformed_df = transform_function(df_in)
    load_function(transformed_df)
    return "Data pipeline executed successfully"
