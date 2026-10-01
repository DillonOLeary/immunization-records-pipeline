"""Port for the delivery sink: the Drive folder staff import from.

Bound to one folder when constructed. Uploading fills the import queue;
listing shows what staff have not yet imported (they delete a file once
it is in Infinite Campus). GoogleDriveSink is the implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DriveSink(Protocol):
    def upload(self, path: Path, name: str) -> str:
        """Upload the file under `name`; returns the remote file id."""
        ...

    def list_filenames(self) -> set[str]:
        """Names of the files this app has in the folder right now."""
        ...
