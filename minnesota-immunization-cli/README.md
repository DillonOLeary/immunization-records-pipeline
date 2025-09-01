# Minnesota Immunization CLI

CLI for interacting with the core library.

## Installation and Development

```bash
# Install with development dependencies
uv pip install -e . ".[dev]"

# Run tests
uv run pytest

# Run linting
ruff .
```

## Usage

To use the CLI, you'll need to have your login information for AISR and a valid config file. An example config file can be found [here](../minnesota-immunization-cli/config/config.json.example).

There are 4 CLI commands:

### `bulk-query`

This submits each school's query file to AISR, so that we can download the vaccination records for each school with the `get-vaccinations` command. You'll need to provide your `AISR_PASSWORD` or have it set in your environment. Command usage:

```bash
minnesota-immunization-cli --config /path/to/config.json bulk-query --username YOUR_AISR_USERNAME
```

### `get-vaccinations`

This downloads vaccination records from AISR for the schools specified in the config file. You'll need to provide your `AISR_PASSWORD` or have it set in your environment. Command usage:

```bash
minnesota-immunization-cli --config /path/to/config.json get-vaccinations --username YOUR_AISR_USERNAME
```

### `transform`

This transforms the vaccination records downloaded from AISR as CSVs into a format Infinite Campus can ingest. Command usage:

```bash
minnesota-immunization-cli --config /path/to/config.json transform
```

### `check-errors`

This checks the logs for errors within the given timeframe/scope. Values for the `scope` can be: `last-day`, `last-week`, `last-month`, or `all`. Command usage:

```bash
minnesota-immunization-cli --config /path/to/config.json check-errors --scope last-week
```

## License

[GNU General Public License](../LICENSE)
