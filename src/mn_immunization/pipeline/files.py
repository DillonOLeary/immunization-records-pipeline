"""File naming conventions shared by the CLI and cloud runtimes."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path


def generate_vaccination_record_filename(school_name: str) -> str:
    """Name for a raw AISR download:
    vaccinations_School_Name_YYYYMMDD_HHMMSS_uniqueid.csv
    """
    clean_school_name = school_name.replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    return f"vaccinations_{clean_school_name}_{timestamp}_{unique_id}.csv"


def transformed_filename(input_file_name: str) -> str:
    """Name for a transformed IC-format file: transformed_<original name>."""
    return f"transformed_{Path(input_file_name).name}"
