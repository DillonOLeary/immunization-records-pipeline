"""Google Cloud Storage: the client, and the ObjectStore over one bucket."""

from __future__ import annotations

from google.api_core.exceptions import NotFound
from google.cloud import storage

from mn_immunization.workflow.ports import ObjectNotFoundError


def get_storage_client() -> storage.Client:
    """Get Google Cloud Storage client"""
    return storage.Client()


class GcsObjectStore:
    """ObjectStore over one bucket (a google.cloud.storage Bucket, or
    anything with a compatible .blob(name) interface)."""

    def __init__(self, bucket) -> None:
        self.bucket = bucket

    def read_text(self, path: str) -> str:
        try:
            return self.bucket.blob(path).download_as_text()
        except NotFound:
            raise ObjectNotFoundError(path) from None

    def write_text(
        self, path: str, text: str, content_type: str = "text/plain"
    ) -> None:
        self.bucket.blob(path).upload_from_string(text, content_type=content_type)
