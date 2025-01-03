"""Unit tests for the main module."""

from pathlib import Path
from unittest.mock import patch

from data_pipeline.__main__ import setup_logging

# pylint: disable=missing-function-docstring


@patch("logging.config.fileConfig")
@patch("datetime.datetime")
# pylint: disable-next=invalid-name
def test_setup_logging(mock_datetime, mock_fileConfig):
    mock_datetime.now.return_value.strftime.return_value = "20250101-12:00:00"

    setup_logging(env="dev", config_dir=Path("mock_config"), log_dir=Path("mock_logs"))

    mock_fileConfig.assert_called_once_with(
        Path("mock_config") / "logging.dev.ini",
        disable_existing_loggers=False,
        defaults={"logfilename": Path("mock_logs") / "20250101-12:00:00.log"},
    )
