"""
Decorator to log the ETL run information
"""

import importlib.metadata
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


def log_etl_run(log_folder: Path):
    """
    Decorator to log the details of an ETL pipeline run.
    """

    def decorator(etl_fn: Callable[[Path, Path], str]):

        def wrapper(input_file: Path, output_folder: Path):
            # Get current timestamp and pipeline version
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            version = importlib.metadata.version(
                "minnesota-immunization-data-pipeline"
            )  # Get package version

            # Generate a unique ID for the run
            run_id = uuid.uuid4().hex[:8]

            # Call the ETL pipeline function
            result_message = etl_fn(input_file, output_folder)

            # Create the log entry
            log_data = {
                "run_id": run_id,
                "input_file": input_file.name,
                "output_folder": str(output_folder),
                "timestamp": timestamp,
                "version": version,
                "result_message": result_message,
            }

            # Ensure the log folder exists
            log_folder.mkdir(parents=True, exist_ok=True)

            # Write the log to a JSON file
            log_file = log_folder / f"log_{run_id}.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=4)

            return result_message

        return wrapper

    return decorator
