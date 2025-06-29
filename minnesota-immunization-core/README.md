# Minnesota Immunization Core

A Python library for processing Minnesota immunization records through ETL (Extract, Transform, Load) operations and AISR (Minnesota Immunization Information Connection) integration.

## Features

- **ETL Pipeline**: Extract, transform, and load immunization data
- **AISR Integration**: Authenticate and interact with Minnesota's immunization system
- **Data Transformation**: Convert AISR format to Infinite Campus format
- **Bulk Operations**: Handle bulk queries and downloads of vaccination records

## Installation

```bash
pip install minnesota-immunization-core
```

## Quick Start

```python
from minnesota_immunization_core import pipeline_factory
from minnesota_immunization_core.etl_workflow import run_etl_workflow

# Create ETL pipeline
config = {
    "input_file": "path/to/aisr_data.csv",
    "output_file": "path/to/transformed_data.csv"
}

extract, transform, load = pipeline_factory.create_etl_pipeline(config)
run_etl_workflow(extract, transform, load)
```

## Architecture

The library implements a functional dependency injection pattern:

- `pipeline_factory.py`: Creates pipeline functions by injecting components
- `etl_workflow.py`: Defines high-level workflow orchestration  
- `extract.py`, `transform.py`, `load.py`: Implement specific data operations
- `aisr/`: Handles Minnesota Immunization Information Connection integration

## Development

```bash
# Install with development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff .
```

## License

GNU General Public License v3.0 or later