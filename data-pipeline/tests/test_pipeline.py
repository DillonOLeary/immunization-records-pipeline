"""
Tests for the pipeline orchestration
"""

# pylint: disable=missing-function-docstring

import pytest

from data_pipeline import Pipeline


@pytest.fixture(name="pipeline_instance")
def pipeline_fixture():
    return Pipeline()


def test_pipeline_run(pipeline_instance):
    assert pipeline_instance.run() == "Data pipeline executed successfully"
