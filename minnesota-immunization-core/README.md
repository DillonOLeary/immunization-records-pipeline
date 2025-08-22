# Minnesota Immunization Core

A Python library for processing Minnesota immunization records through ETL (Extract, Transform, Load) operations and AISR (Minnesota Immunization Information Connection) integration.

## Features

- **ETL Pipeline**: Extract, transform, and load immunization data
- **AISR Integration**: Authenticate and interact with Minnesota's immunization system
- **Data Transformation**: Convert AISR format to Infinite Campus format
- **Bulk Operations**: Handle bulk queries and downloads of vaccination records

## Installation

```bash
uv venv
uv pip install minnesota-immunization-core
```

## Development

```bash
# Install with development dependencies
uv pip install -e ".[dev]"

# Run tests
uv run pytest

# Run linting
ruff .
```

## Usage

You'll interact with the core library throught the CLI or Google Cloud modules. Refer to the readmes in those directories for usage information.

## Architecture

The library implements a functional dependency injection pattern:

- `pipeline_factory.py`: Creates pipeline functions by injecting components
- `etl_workflow.py`: Defines high-level workflow orchestration
- `extract.py`, `transform.py`, `load.py`: Implement specific data operations
- `aisr/`: Handles Minnesota Immunization Information Connection integration

## License

[GNU General Public License](../LICENSE)
