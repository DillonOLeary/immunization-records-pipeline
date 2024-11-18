"""
This file runs the immunization data pipeline.
"""

from collections.abc import Callable

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
