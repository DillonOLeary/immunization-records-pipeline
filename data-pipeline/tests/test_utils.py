"""
Utils used for testing the data pipeline.
"""

import subprocess


def execute_transform_subprocess(input_folder, output_folder, logs_folder):
    """
    Execute the CLI as a subprocess.
    """
    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "data_pipeline",
            "--input_folder",
            input_folder,
            "--output_folder",
            output_folder,
            "--logs_folder",
            logs_folder,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    return result
