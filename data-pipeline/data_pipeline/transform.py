"""
Transforms the immunization records
"""

from pandas import DataFrame


def transform_data_from_aisr_to_infinite_campus(df: DataFrame) -> DataFrame:
    """
    Transform the data as required by infinite campus
    The remaining fields after the transformation should be:
    - id_1, id_2, vaccine_group_name and vaccination_date
    - vaccination_date should be formatted with like MM/DD/YYYY
    """
    return df
