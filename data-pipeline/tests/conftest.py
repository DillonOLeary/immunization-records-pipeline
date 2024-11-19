"""
Pytest utils
"""

from pathlib import Path

import pytest


@pytest.fixture(name="folders")
def input_output_manifest_folders():
    """
    Allows tests to use input, output, and manifests folders
    """
    input_folder = Path(".") / "tests" / "test_input"
    output_folder = Path(".") / "tests" / "test_output"
    manifest_folder = Path(".") / "tests" / "test_manifest"

    # Create directories
    for folder in [input_folder, output_folder, manifest_folder]:
        folder.mkdir(parents=True, exist_ok=True)

    # Yield the folders for test usage
    yield input_folder, output_folder, manifest_folder

    # Cleanup after the test
    for folder in [input_folder, output_folder, manifest_folder]:
        if folder.exists():
            for file in folder.iterdir():
                file.unlink()
            folder.rmdir()
