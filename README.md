# Immunization Records Pipeline
A data pipeline that minimizes manual effort when extracting immunization records from the Minnesota Department of Health, transforming them, and loading them into the student information system, Infinite Campus.

## Running the AISR to Infinite Campus CSV Transformation
Instructions for MacOS users:
1. [Download the code locally](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository)
1. Open terminal and cd into the newly downloaded code
1. Run `./setup_and_run_mac.sh`

You can also run the script without the folder popup windows:
1. [Install Poetry](https://python-poetry.org/docs/)
1. From the directory that that the project is installed, run `cd immunization-records-project/data-pipeline`
1. Then run `poetry install --only main` to get the project dependencies. You only need to run this once.
1. Then you can run the project with `poetry run python data_pipeline --input_folder "<input_folder_path>" --output_folder "<output_folder_path>" --log_folder <log_folder_path>`
