"""
Unit tests for the log analyzer module.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from data_pipeline.log_analyzer import LogErrorAnalyzer


@pytest.fixture
def sample_log_content():
    """Create sample log content for testing."""
    now = datetime.now()
    yesterday = now - timedelta(days=1)
    last_week = now - timedelta(days=7)
    last_month = now - timedelta(days=30)
    
    # Log entries with different timestamps - one per line
    log_entries = []
    
    # Today's ERROR
    log_entries.append(f"{now.strftime('%Y-%m-%d %H:%M:%S')},123 - ERROR - data_pipeline.cli - get_school_query_information:230 - Query file not found for school Test School")
    
    # Yesterday's ERROR 
    log_entries.append(f"{yesterday.strftime('%Y-%m-%d %H:%M:%S')},456 - ERROR - data_pipeline.extract - extract_function:45 - Failed to extract data")
    
    # Last week's ERROR
    log_entries.append(f"{last_week.strftime('%Y-%m-%d %H:%M:%S')},789 - ERROR - data_pipeline.transform - transform_function:78 - Invalid data format")
    
    # Last month's ERROR
    log_entries.append(f"{last_month.strftime('%Y-%m-%d %H:%M:%S')},321 - ERROR - data_pipeline.load - load_function:92 - Failed to write to output file")
    
    # Today's INFO (should be ignored by error search)
    log_entries.append(f"{now.strftime('%Y-%m-%d %H:%M:%S')},654 - INFO - data_pipeline.cli - handle_transform_command:346 - Transform command started")
    
    return log_entries


@pytest.fixture
def mock_log_folder(tmp_path, sample_log_content):
    """Create a mock log folder with sample log files."""
    log_folder = tmp_path / "logs"
    log_folder.mkdir(exist_ok=True)
    
    # Create a sample log file
    log_file = log_folder / "app.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(sample_log_content))
    
    return log_folder


def test_log_analyzer_init(mock_log_folder):
    """Test the initialization of the LogErrorAnalyzer."""
    analyzer = LogErrorAnalyzer(mock_log_folder)
    assert analyzer.log_folder == mock_log_folder


def test_get_log_files(mock_log_folder):
    """Test getting log files from the folder."""
    analyzer = LogErrorAnalyzer(mock_log_folder)
    log_files = analyzer._get_log_files()
    
    assert len(log_files) == 1
    assert log_files[0].name == "app.log"


def test_parse_log_line():
    """Test parsing a log line into its components."""
    analyzer = LogErrorAnalyzer(Path())  # Path doesn't matter for this test
    line = "2025-03-02 15:30:45,123 - ERROR - data_pipeline.cli - get_school_query_information:230 - Query file not found"
    
    timestamp, level, module, function, message = analyzer._parse_log_line(line)
    
    assert isinstance(timestamp, datetime)
    assert timestamp.year == 2025
    assert timestamp.month == 3
    assert timestamp.day == 2
    assert level == "ERROR"
    assert module == "data_pipeline.cli"
    assert function == "get_school_query_information:230"
    assert message == "Query file not found"


def test_parse_log_line_invalid_format():
    """Test parsing a log line with invalid format."""
    analyzer = LogErrorAnalyzer(Path())
    line = "This is not a valid log line"
    
    with pytest.raises(ValueError):
        analyzer._parse_log_line(line)


def test_get_time_range():
    """Test getting time ranges for different scopes."""
    analyzer = LogErrorAnalyzer(Path())
    now = datetime.now()
    
    # Test different scopes
    day_range = analyzer._get_time_range("last-day")
    week_range = analyzer._get_time_range("last-week")
    month_range = analyzer._get_time_range("last-month")
    all_range = analyzer._get_time_range("all")
    
    # Approximate comparisons due to tiny time differences during test execution
    assert abs((now - day_range).total_seconds() - 86400) < 10  # Within 10 seconds of a day
    assert abs((now - week_range).total_seconds() - 604800) < 10  # Within 10 seconds of a week
    assert abs((now - month_range).total_seconds() - 2592000) < 10  # Within 10 seconds of 30 days
    assert all_range == datetime.min


def test_analyze_errors_last_day(mock_log_folder, sample_log_content):
    """Test analyzing errors from the last day."""
    analyzer = LogErrorAnalyzer(mock_log_folder)
    
    # Mock the time range to ensure we get exactly what we expect
    yesterday = datetime.now() - timedelta(days=1, hours=1)  # Add buffer for test execution time
    with mock.patch.object(analyzer, '_get_time_range', return_value=yesterday):
        errors = analyzer.analyze_errors("last-day")
        
        # Should find at least the current day's error and yesterday's error
        assert len(errors) >= 2
        assert all(error["level"] == "ERROR" for error in errors)
        
        # Check that we have the expected errors (might be in different order due to timestamp sorting)
        messages = [error["message"] for error in errors]
        assert any("Query file not found" in msg for msg in messages)
        assert any("Failed to extract data" in msg for msg in messages)


def test_analyze_errors_last_week(mock_log_folder, sample_log_content):
    """Test analyzing errors from the last week."""
    analyzer = LogErrorAnalyzer(mock_log_folder)
    
    # Mock the time range to ensure we get exactly what we expect
    last_week = datetime.now() - timedelta(days=7, hours=1)  # Add buffer for test execution time
    with mock.patch.object(analyzer, '_get_time_range', return_value=last_week):
        errors = analyzer.analyze_errors("last-week")
        
        # Should find 3 errors from the last week
        assert len(errors) >= 3
        assert all(error["level"] == "ERROR" for error in errors)
        
        # Check that we have the expected errors
        messages = [error["message"] for error in errors]
        assert any("Query file not found" in msg for msg in messages)
        assert any("Failed to extract data" in msg for msg in messages)
        assert any("Invalid data format" in msg for msg in messages)


def test_analyze_errors_all(mock_log_folder, sample_log_content):
    """Test analyzing all errors regardless of time."""
    analyzer = LogErrorAnalyzer(mock_log_folder)
    
    # Use actual "all" time range
    errors = analyzer.analyze_errors("all")
    
    # Should find all 4 ERROR entries
    assert len(errors) == 4
    assert all(error["level"] == "ERROR" for error in errors)
    
    # Check that we have all expected errors
    messages = [error["message"] for error in errors]
    assert any("Query file not found" in msg for msg in messages)
    assert any("Failed to extract data" in msg for msg in messages)
    assert any("Invalid data format" in msg for msg in messages)
    assert any("Failed to write to output file" in msg for msg in messages)


def test_get_error_summary(mock_log_folder, sample_log_content):
    """Test getting a summary of errors."""
    analyzer = LogErrorAnalyzer(mock_log_folder)
    summary = analyzer.get_error_summary("all")
    
    assert summary["total_errors"] == 4
    assert len(summary["errors_by_module"]) == 4
    assert "data_pipeline.cli" in summary["errors_by_module"]
    assert "data_pipeline.extract" in summary["errors_by_module"]
    assert "data_pipeline.transform" in summary["errors_by_module"]
    assert "data_pipeline.load" in summary["errors_by_module"]


def test_empty_log_folder(tmp_path):
    """Test handling an empty log folder."""
    empty_folder = tmp_path / "empty_logs"
    empty_folder.mkdir(exist_ok=True)
    
    analyzer = LogErrorAnalyzer(empty_folder)
    errors = analyzer.analyze_errors()
    
    assert len(errors) == 0


def test_no_matching_errors(tmp_path):
    """Test when there are no matching errors in the time range."""
    # Create a clean log folder
    log_folder = tmp_path / "empty_logs"
    log_folder.mkdir(exist_ok=True)
    
    # Create a log with only old errors
    log_file = log_folder / "old_errors.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("2020-01-01 12:00:00,123 - ERROR - module - function - Old error message\n")
    
    analyzer = LogErrorAnalyzer(log_folder)
    
    # Use a very recent time range
    with mock.patch.object(analyzer, '_get_time_range', return_value=datetime.now() - timedelta(hours=1)):
        errors = analyzer.analyze_errors("last-day")
        assert len(errors) == 0