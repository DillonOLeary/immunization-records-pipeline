import os
import subprocess


def test_cli_runs_for_all_test_files(tmp_path):
    output_folder = tmp_path / 'test_output_folder'
    output_folder.mkdir()
    input_folder = tmp_path / 'test_input_folder'
    input_folder.mkdir()

    test_file = os.path.join(input_folder, 'test_file.csv')
    with open(test_file, 'w') as f:
        f.write("id_1|id_2|vaccine_group_name|vaccination_date\n")
        f.write("123|456|COVID-19|11/17/2024\n")
        f.write("789|101|Flu|11/16/2024\n")
        f.write("112|131|COVID-19|11/15/2024\n")

    result = subprocess.run(
        ['poetry', 'run', 'python', 'data_pipeline', '--input_folder', input_folder, '--output_folder', output_folder],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # Check that the command ran successfully
    assert result.returncode == 0, f"CLI failed with error: {result.stderr.decode()}"

    # Ensure output folder contains transformed files
    assert len(os.listdir(output_folder)) > 0, "No files were created in the output folder"
    
    # TODO should I be making the directories?