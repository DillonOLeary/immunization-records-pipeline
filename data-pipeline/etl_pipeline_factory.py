from collections.abc import Callable
from pathlib import Path

from data_pipeline.etl_pipeline import run_etl


def create_etl_pipeline(extract, transform, load) -> Callable[[Path, Path], str]:
    """
    Creates an ETL pipeline by injecting the extract, transform, and load functions.

    Args:
        extract (Callable[[], pd.DataFrame]): Function to extract data from input.
        transform (Callable[[pd.DataFrame], pd.DataFrame]):
            Function to transform the extracted data.
        load (Callable[[pd.DataFrame], None]):
            Function to load the transformed data to a destination.

    Returns:
        Callable[[Path, Path], str]: A function that runs the full ETL pipeline on a file.
    """

    def etl_fn(input_file: Path, output_folder: Path) -> str:
        """
        Runs the ETL pipeline on a single input file.

        Args:
            input_file (Path): The input file to process.
            output_folder (Path): The folder where output will be saved.

        Returns:
            str: A success message if the ETL pipeline completes successfully.
        """
        return run_etl(
            extract=lambda: extract(input_file),
            transform=transform,
            load=lambda df: load(df, output_folder, input_file.name),
        )

    return etl_fn