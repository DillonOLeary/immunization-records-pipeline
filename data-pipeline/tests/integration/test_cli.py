import os
import subprocess
from pathlib import Path


def test_cli_runs_for_all_test_files(tmp_path):
    output_folder = tmp_path / 'test_output_folder'
    output_folder.mkdir()
    input_folder = tmp_path / 'test_input_folder'
    input_folder.mkdir()

    test_file = os.path.join(input_folder, 'test_file.txt')
    with open(test_file, 'w') as f:
        f.write("Sample data to transform")

    # Run the CLI command, assuming it's a Python script or command
    result = subprocess.run(
        ['poetry', 'run', 'python', 'data_pipeline', '--input_folder', input_folder, '--output_folder', output_folder],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # Check that the command ran successfully
    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Ensure output folder contains transformed files
    assert os.path.isdir(output_folder), "Output folder was not created"
    assert len(os.listdir(output_folder)) > 0, "No files were created in the output folder"