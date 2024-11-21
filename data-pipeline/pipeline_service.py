from pathlib import Path

from data_pipeline.etl_pipeline import run_etl_on_folder
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.manifest_generator import log_etl_run
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus
from etl_pipeline_factory import create_etl_pipeline


class AisrToIcPipelineService:
    """
    Service class responsible for managing the ETL (Extract, Transform, Load) pipeline 
    from AISR CSV data to Infinite Campus. This class handles the creation, validation, 
    and execution of the ETL pipeline to transform the data.
    """

    def __init__(self, input_folder: Path, output_folder: Path, manifest_folder: Path):
        """
        Initialize the AISR to Infinite Campus ETL pipeline service.

        Parameters:
        - input_folder (Path): Path to the folder containing AISR CSV files for extraction.
        - output_folder (Path): Path to the folder where transformed data should be saved.
        - manifest_folder (Path): Path to the folder where ETL process logs will be stored.
        """
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.manifest_folder = manifest_folder

    def validate_folders(self) -> bool:
        """
        Validates that the input, output, and manifest folders all exist.

        Returns:
        - bool: True if all folders are valid, otherwise False.
        """
        return all([self.input_folder.exists(), self.output_folder.exists(), self.manifest_folder.exists()])

    def create_pipeline(self):
        """
        Constructs and returns the ETL pipeline based on defined extraction, transformation, 
        and loading functions.

        Returns:
        - function: An ETL pipeline with logging capabilities.
        """
        etl_pipeline = create_etl_pipeline(
            extract=read_from_aisr_csv,
            transform=transform_data_from_aisr_to_infinite_campus,
            load=write_to_infinite_campus_csv,
        )
        return log_etl_run(self.manifest_folder)(etl_pipeline)

    def run_pipeline(self, etl_pipeline_with_logging):
        """
        Executes the ETL pipeline to transform AISR CSV data into Infinite Campus format.

        Parameters:
        - etl_pipeline_with_logging (function): The ETL pipeline with logging functionality.

        Returns:
        - None
        """
        run_etl_on_folder(
            input_folder=self.input_folder,
            output_folder=self.output_folder,
            etl_fn=etl_pipeline_with_logging,
        )
