"""
Tests for the main app
"""

# pylint: disable=missing-function-docstring

from data_transform.main import App


def test_hello_world():
    assert App.run() == "hello world"
