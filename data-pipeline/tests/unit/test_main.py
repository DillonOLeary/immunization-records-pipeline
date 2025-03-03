"""Unit tests for the main module."""

from pathlib import Path
from unittest.mock import patch

from data_pipeline.__main__ import setup_logging

# pylint: disable=missing-function-docstring


@patch("logging.config.fileConfig")
# pylint: disable-next=invalid-name
def test_setup_logging(mock_fileConfig):

    setup_logging(env="dev", log_dir=Path("mock_logs"))

    mock_fileConfig.assert_called_once_with(
        Path("config") / "logging.dev.ini",
        disable_existing_loggers=False,
        defaults={"logfilename": str(Path("mock_logs") / "app.log")},
    )
