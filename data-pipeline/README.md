<h1 align="center">🩺⚙️ Immunization Records Pipeline 🩺⚙️</h1>

<h4 align="center">A data pipeline that minimizes manual effort when extracting immunization records from the Minnesota Department of Health, transforming them, and loading them into the student information system, Infinite Campus.</h4>

## Features

- **Transform Command**: Convert immunization data from AISR format to Infinite Campus format
- **Bulk Query Command**: Submit bulk queries to the AISR system
- **Get Vaccinations Command**: Download vaccination records from AISR

## Configuration

Create a JSON configuration file with the following structure:

```json
{
  "paths": {
    "input_folder": "path/to/aisr_downloads",  # Folder containing AISR downloaded files
    "output_folder": "path/to/output",         # Folder where transformed files will be saved
    "logs_folder": "path/to/logs"              # Folder for application logs
  },
  "api": {
    "auth_base_url": "https://authenticator-url",
    "aisr_api_base_url": "https://api-url"
  },
  "schools": [
    {
      "name": "School Name",
      "id": "school-id",
      "classification": "N",
      "email": "contact@example.com"
    }
  ]
}
```

## Usage

### Transform Command

Transforms immunization data from AISR format to Infinite Campus format:

```bash
python data_pipeline --config path/to/config.json transform
```

### Bulk Query Command

Submits a bulk query to AISR for immunization records:

```bash
python data_pipeline --config path/to/config.json bulk-query --username your-username
```

The password will be requested interactively or can be provided via the `AISR_PASSWORD` environment variable.

### Get Vaccinations Command

Downloads vaccination records from AISR:

```bash
python data_pipeline --config path/to/config.json get-vaccinations --username your-username
```

## Developer Setup

### Environment Setup
Developer setup is easy with Dev Containers!
1. [Download the code locally](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository)
1. Ensure [VS Code](https://code.visualstudio.com/) is installed
1. Open the repository in VS Code
1. Follow the tutorial [here](https://code.visualstudio.com/docs/devcontainers/tutorial) to set up Dev Containers.
1. Run the command (View->Command Palette) `Dev Containers: Reopen in Container`
   - This may take several minutes the first time

### Using Poetry for Development
This project uses Poetry for dependency management:

```bash
# Install dependencies
poetry install

# Run the application
poetry run python data_pipeline --config config/config.json transform

# Run tests
poetry run pytest

# Run specific tests
poetry run pytest tests/unit/
poetry run pytest tests/integration/
```

### Project Structure
- `data_pipeline/`: Main package directory
  - `__main__.py`: Entry point for the application
  - `cli.py`: Command-line interface and handlers
  - `aisr/`: AISR API interaction
    - `actions.py`: API actions for queries and downloads
    - `authenticate.py`: Authentication with AISR
  - `io/`: Input/output operations
    - `extract.py`: Data extraction functions
    - `load.py`: Data loading functions
  - `etl_workflow.py`: Core ETL workflow
  - `transform.py`: Data transformation functions
  - `pipeline_factory.py`: Factory functions for creating pipelines
- `tests/`: Test directory
  - `unit/`: Unit tests
  - `integration/`: Integration tests
  - `mock_server.py`: Mock server for testing
- `config/`: Configuration files
- `logs/`: Application logs