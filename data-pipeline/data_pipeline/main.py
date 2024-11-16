"""
Inject dependencies and run pipeline
"""

from pathlib import Path

from data_pipeline import DataPipeline
from data_pipeline.csv_read import read_from_aisr_csv
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus

if __name__ == "__main__":
    file_in_path = Path("tests/mock_data/mock_aisr_download.csv")
    file_out_path = Path("output/mock_transformed_data.csv")
    dp = DataPipeline(
        data_loader=lambda: read_from_aisr_csv(file_in_path),
        transformation_function=transform_data_from_aisr_to_infinite_campus,
    )

    # Assuming the pipeline runs and the DataFrame is returned after transformation
    df_transformed = dp.run()

    # Write the transformed DataFrame to a CSV with a comma separator
    df_transformed.to_csv(file_out_path, index=False, sep=",")
