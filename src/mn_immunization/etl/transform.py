"""
Transforms the immunization records
"""

import pandas as pd


def transform_data_from_aisr_to_infinite_campus(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Transform the data as required by Infinite Campus.

    The remaining fields after the transformation should be:
    - id_1, id_2, vaccine_group_name, and vaccination_date
    - vaccination_date should be formatted like MM/DD/YYYY

    Args:
        df (DataFrame): Input dataframe containing the immunization records.

    Returns:
        DataFrame: Transformed dataframe containing only the necessary columns with
        formatted date.
    # TODO some sort of validation
    """
    required_columns = ["id_1", "id_2", "vaccine_group_name", "vaccination_date"]
    # Copying to avoid modifying the input dataframe directly.
    df_transformed = df_in[required_columns].copy()
    df_transformed["vaccination_date"] = pd.to_datetime(
        df_transformed["vaccination_date"]
    ).dt.strftime("%m/%d/%Y")

    return df_transformed
