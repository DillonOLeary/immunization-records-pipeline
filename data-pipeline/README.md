<h1 align="center">🩺⚙️ Immunization Records Pipeline 🩺⚙️</h1>

<h4 align="center">A data pipeline that minimizes manual effort when extracting immunization records from the Minnesota Department of Health, transforming them, and loading them into the student information system, Infinite Campus.</h4>

## Running the AISR to Infinite Campus CSV Transformation
1. Make sure you have Python 3 installed on your computer.
1. Open your terminal and paste the command below:

   ```bash
   pip install minnesota-immunization-data-pipeline

   # If you get an error about 'pip not found', just replace pip with pip3.
   ```
1. Then you can run the project with 
   ```bash
   minnesota-immunization-data-pipeline --input_folder "<input_folder_path>" --output_folder "<output_folder_path>" --log_folder <log_folder_path>
   ```

## Developer Setup
Developer setup is easy with Dev Containers!
1. [Download the code locally](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository)
1. Ensure [VS Code](https://code.visualstudio.com/) is installed
1. Follow the tutorial [here](https://code.visualstudio.com/docs/devcontainers/tutorial) to set up Dev Containers.
1. Run the command `Dev Containers: Reopen in Container`
