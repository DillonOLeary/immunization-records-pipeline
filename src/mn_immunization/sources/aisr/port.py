"""Port for immunization record sources.

AisrClient is today's implementation. A second source (another state
registry, a different bulk interface after MIIC's website change) implements
this protocol and slots into the composition root without touching callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from mn_immunization.sources.aisr.actions import SchoolQueryInformation


class ImmunizationSource(Protocol):
    def submit_roster_query(self, school: SchoolQueryInformation) -> None: ...

    def download_latest_records(self, school_id: str, output_path: Path) -> str: ...
