"""
This file runs the immunization data pipeline.
"""

from collections.abc import Callable

import pandas as pd


class Orchestrator:
    """
    Orchestrate the ETL
    """

    def __init__(
        self,
        data_loader: Callable[[], pd.DataFrame],
        transformation_function: Callable[[pd.DataFrame], pd.DataFrame],
    ):
        """
        Initialize the DataPipeline with a data loader and transformation function.

        Args:
            data_loader (Callable[[], pd.DataFrame]): Function that loads and returns a DataFrame.
            transformation_function (Callable[[pd.DataFrame], pd.DataFrame]):
                Function that takes a DataFrame as input and returns a transformed DataFrame.
        """
        self.data_loader = data_loader
        self.transformation_function = transformation_function

    def run(self):
        """
        Run project
        """
        df_in = self.data_loader()
        transformed_df = self.transformation_function(df_in)

        # TODO add more steps here (e.g., save data, further processing)
        print(transformed_df)

        return "Data pipeline executed successfully"
