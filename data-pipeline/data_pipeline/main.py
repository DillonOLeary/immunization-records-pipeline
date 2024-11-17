"""
Inject dependencies and run pipeline
"""

from pathlib import Path

from data_pipeline.data_flow import run_pipeline
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus

if __name__ == "__main__":
    # pylint: disable=invalid-name
    file_in_path = Path(".") / "tests" / "mock_data" / "mock_aisr_download.csv"
    file_out_path = Path(".") / "output" / "mock_transformed_data.csv"

    result_message = run_pipeline(
        extract_function=lambda: read_from_aisr_csv(file_in_path),
        transform_function=transform_data_from_aisr_to_infinite_campus,
        load_function=lambda df: write_to_infinite_campus_csv(df, file_out_path),
    )

    print(result_message)
