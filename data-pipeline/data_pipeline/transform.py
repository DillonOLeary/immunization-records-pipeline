"""
Transforms the immunization records
"""

import pandas as pd


def transform_data_from_aisr_to_infinite_campus(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform the data as required by Infinite Campus.

    The remaining fields after the transformation should be:
    - id_1, id_2, vaccine_group_name, and vaccination_date
    - vaccination_date should be formatted like MM/DD/YYYY

    Args:
        df (DataFrame): Input dataframe containing the immunization records.

    Returns:
        DataFrame: Transformed dataframe containing only the necessary columns with formatted date.
    """
    # Define the list of expected columns
    required_columns = ["id_1", "id_2", "vaccine_group_name", "vaccination_date"]

    # Ensure the dataframe only contains the required columns
    df = df[required_columns]

    # Format the 'vaccination_date' column to MM/DD/YYYY
    df["vaccination_date"] = pd.to_datetime(df["vaccination_date"]).dt.strftime(
        "%m/%d/%Y"
    )

    return df
