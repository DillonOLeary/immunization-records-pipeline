#!/bin/bash

# Run the Python script
poetry run python data_pipeline/main.py tests/mock_data/mock_aisr_download.csv output/mock_transformed_data.csv