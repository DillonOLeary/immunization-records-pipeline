"""
Module for analyzing log files to find errors.

This module provides functionality to efficiently search log files for errors
and present them in a structured way.
"""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# Regular expression pattern for log line parsing
# Format: YYYY-MM-DD HH:MM:SS,mmm - LEVEL - MODULE - FUNCTION:LINE - MESSAGE
LOG_PATTERN = (
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - ([^-]+) - ([^-]+) - (.+)"
)


class LogErrorAnalyzer:
    """
    Class for analyzing log files to find and report errors.

    This analyzer uses efficient techniques to scan log files and extract
    relevant error information within the specified time frame.
    """

    def __init__(self, log_folder: Path):
        """
        Initialize the log analyzer with the path to the log folder.

        Args:
            log_folder: Path to the folder containing log files
        """
        self.log_folder = log_folder

    def _get_log_files(self) -> List[Path]:
        """
        Get all log files in the log folder.

        Returns:
            List of paths to log files
        """
        return list(self.log_folder.glob("*.log"))

    def _parse_log_line(self, line: str) -> Tuple[datetime, str, str, str, str]:
        """
        Parse a log line into its components.

        Args:
            line: A single line from a log file

        Returns:
            Tuple of (timestamp, level, module, function, message)

        Raises:
            ValueError: If the line doesn't match the expected format
        """
        match = re.match(LOG_PATTERN, line)
        if not match:
            raise ValueError(f"Line doesn't match expected format: {line}")

        timestamp_str, level, module, function, message = match.groups()
        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")

        return timestamp, level, module.strip(), function.strip(), message.strip()

    def _is_in_time_range(self, timestamp: datetime, start_time: datetime) -> bool:
        """
        Check if a timestamp is within the specified time range.

        Args:
            timestamp: The timestamp to check
            start_time: The start time of the range

        Returns:
            True if the timestamp is within range, False otherwise
        """
        return timestamp >= start_time

    def _get_time_range(self, scope: str) -> datetime:
        """
        Get the start time based on the specified scope.

        Args:
            scope: One of 'last-day', 'last-week', 'last-month', or 'all'

        Returns:
            Start time for the specified scope
        """
        now = datetime.now()

        if scope == "last-day":
            return now - timedelta(days=1)
        if scope == "last-week":
            return now - timedelta(weeks=1)
        if scope == "last-month":
            return now - timedelta(days=30)
        # all
        return datetime.min

    def analyze_errors(self, scope: str = "last-week") -> List[Dict]:
        """
        Analyze log files for errors within the specified time scope.

        This method efficiently scans log files looking for ERROR level entries
        within the specified time range.

        Args:
            scope: Time scope for analysis ('last-day', 'last-week', 'last-month', 'all')

        Returns:
            List of dictionaries containing error information
        """
        start_time = self._get_time_range(scope)
        errors = []
        log_files = self._get_log_files()

        if not log_files:
            logger.warning("No log files found in %s", self.log_folder)
            return []

        for log_file in log_files:
            # For very large files, we could use more efficient techniques like:
            # 1. Binary search to approximate start position if logs are in chronological order
            # 2. Reversed reading for recent logs
            # But for simplicity and since log files are typically manageable size:
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if "ERROR" not in line:
                            continue

                        try:
                            timestamp, level, module, function, message = (
                                self._parse_log_line(line)
                            )
                            if level != "ERROR":
                                continue

                            if self._is_in_time_range(timestamp, start_time):
                                errors.append(
                                    {
                                        "timestamp": timestamp,
                                        "level": level,
                                        "module": module,
                                        "function": function,
                                        "message": message,
                                        "file": log_file.name,
                                    }
                                )
                        except ValueError:
                            # Skip lines that don't match our expected format
                            continue
            except (IOError, PermissionError, UnicodeDecodeError) as e:
                logger.error("Error reading log file %s: %s", log_file, e)

        # Sort errors by timestamp, most recent first
        return sorted(errors, key=lambda x: x["timestamp"], reverse=True)

    def get_error_summary(self, scope: str = "last-week") -> Dict:
        """
        Generate a summary of errors within the specified time scope.

        Args:
            scope: Time scope for analysis ('last-day', 'last-week', 'last-month', 'all')

        Returns:
            Dictionary with error summary information
        """
        errors = self.analyze_errors(scope)

        by_module = {}
        for error in errors:
            module = error["module"]
            if module not in by_module:
                by_module[module] = []
            by_module[module].append(error)

        return {
            "total_errors": len(errors),
            "errors_by_module": {
                module: len(module_errors)
                for module, module_errors in by_module.items()
            },
            "errors": errors,
        }
