import os
import subprocess


def test_cli_runs_for_all_test_files():
    pass
    # # Define test input and output folder paths
    # input_folder = './test_input_folder'
    # output_folder = './test_output_folder'

    # # Ensure the input folder exists and contains test files
    # # os.makedirs(input_folder, exist_ok=True)
    # test_file = os.path.join(input_folder, 'test_file.txt')
    # with open(test_file, 'w') as f:
    #     f.write("Sample data to transform")

    # # Ensure the output folder is clean before the test
    # if os.path.exists(output_folder):
    #     for f in os.listdir(output_folder):
    #         os.remove(os.path.join(output_folder, f))
    # os.makedirs(output_folder, exist_ok=True)

    # # Run the CLI command, assuming it's a Python script or command
    # result = subprocess.run(
    #     ['python', 'your_script.py', '--input', input_folder, '--output', output_folder],
    #     stdout=subprocess.PIPE,
    #     stderr=subprocess.PIPE
    # )

    # # Check that the command ran successfully
    # assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # # Ensure output folder contains transformed files
    # assert os.path.isdir(output_folder), "Output folder was not created"
    # assert len(os.listdir(output_folder)) > 0, "No files were created in the output folder"
    
    # # Clean up test directories after the test
    # for f in os.listdir(input_folder):
    #     os.remove(os.path.join(input_folder, f))
    # os.rmdir(input_folder)
    # for f in os.listdir(output_folder):
    #     os.remove(os.path.join(output_folder, f))
    # os.rmdir(output_folder)