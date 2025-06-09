"""
Decorator to record the ETL run information
"""

import importlib.metadata
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


def run_etl_with_metadata_generation(metadata_folder: Path):
    """
    Decorator to record the metadata of an ETL pipeline run.
    """

    def decorator(etl_fn: Callable[[Path, Path], str]):
        def wrapper(input_file: Path, output_folder: Path):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            version = importlib.metadata.version(
                "minnesota-immunization-core"
            )  # Get package version

            # Generate a unique ID for the run
            run_id = uuid.uuid4().hex[:8]

            result_message = etl_fn(input_file, output_folder)

            metadata = {
                "run_id": run_id,
                "input_file": input_file.name,
                "output_folder": str(output_folder),
                "timestamp": timestamp,
                "version": version,
                "result_message": result_message,
            }

            metadata_folder.mkdir(parents=True, exist_ok=True)

            metadata_file = metadata_folder / f"execution_metadata_{run_id}.json"
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4)

            return result_message

        return wrapper

    return decorator
