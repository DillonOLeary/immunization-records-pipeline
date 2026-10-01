"""Port for the district's object store: config, rosters, the master.

The pipeline reads and writes a handful of named text objects in one
bucket; this is all it may know about storage. GcsObjectStore is the
implementation.
"""

from __future__ import annotations

from typing import Protocol


class ObjectNotFoundError(Exception):
    """No object at that path. The message is the path, never content."""


class ObjectStore(Protocol):
    def read_text(self, path: str) -> str:
        """The object's text; raises ObjectNotFoundError if absent."""
        ...

    def write_text(
        self, path: str, text: str, content_type: str = "text/plain"
    ) -> None: ...
