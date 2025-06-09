# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

This repository is organized as a Python mono-repo for Minnesota Immunization Records processing, with these main components:

1. **minnesota-immunization-core**: Core library implementing the ETL pipeline (Extract, Transform, Load) for processing immunization records, plus AISR (MN immunization system) integration
2. **minnesota-immunization-cli**: Command-line interface for interacting with the core library
3. **minnesota-immunization-cloud**: Cloud function for processing immunization records
4. **minnesota-immunization-infra**: Terraform infrastructure code

## Development Commands

### Setup Environment

```bash
# Install all packages in development mode with uv
cd minnesota-immunization-core
uv pip install -e ".[dev]"
cd ../minnesota-immunization-cli
uv pip install -e ".[dev]"
cd ../minnesota-immunization-cloud
uv pip install -e ".[dev]"
```

### Run Tests

```bash
# Run all tests for a package
cd minnesota-immunization-core
uv run pytest

# Run specific test file
uv run pytest tests/test_transform.py

# Run specific test with verbose output
uv run pytest tests/test_transform.py::test_function_name -v
```

### Linting and Type Checking

```bash
# Run ruff linter
cd minnesota-immunization-core  # (or any other package directory)
uv run ruff .

# Apply fixes automatically
uv run ruff . --fix
```

## Architecture

### Core Data Pipeline

The project implements an ETL (Extract, Transform, Load) pipeline for immunization records:

1. **Extract**: Reads data from AISR (Minnesota Immunization Information Connection)
2. **Transform**: Converts AISR format to Infinite Campus format
3. **Load**: Saves data to CSV files for import into school management systems

The system uses a functional dependency injection pattern where:
- `pipeline_factory.py` creates pipeline functions by injecting components
- `etl_workflow.py` defines the high-level workflow orchestration
- The ETL components (extract.py, transform.py, load.py) implement the specific data operations

### AISR Integration

The `aisr` module handles interactions with the Minnesota Immunization Information Connection (MIIC):

1. `authenticate.py`: Handles login/logout with the AISR authentication API
2. `actions.py`: Implements specific actions like bulk querying and downloading vaccination records

### CLI Application

The CLI provides commands for:

1. `transform`: Process CSV files from AISR downloads into the format needed for school systems
2. `bulk-query`: Submit queries to AISR to find student immunization records 
3. `get-vaccinations`: Download vaccination records from AISR

### Configuration

The application uses JSON configuration files with:
- API endpoints for authentication and data access
- School information including IDs and query file paths
- File paths for input/output/logging