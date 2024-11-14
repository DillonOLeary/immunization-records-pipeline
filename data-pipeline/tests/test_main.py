"""
Tests for the main app
"""

# pylint: disable=missing-function-docstring

from data_pipeline.main import run


def test_hello_world():
    assert run() == "hello world"
