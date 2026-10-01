"""Test doubles shared across the suite.

FakeBucket stands in for a google.cloud.storage Bucket at the surface the
pipeline's GCS adapters use. It honors the one semantic the claim
guarantee rests on, `if_generation_match=0` (create only if absent), and
raises the real NotFound / PreconditionFailed exceptions, so adapter code
under test takes its real error paths.
"""

from __future__ import annotations

from pathlib import Path

from google.api_core.exceptions import NotFound, PreconditionFailed


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str):
        self.bucket = bucket
        self.name = name

    @property
    def generation(self) -> int | None:
        return self.bucket.generations.get(self.name)

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        if if_generation_match == 0 and self.name in self.bucket.objects:
            raise PreconditionFailed(f"object {self.name} already exists")
        self.bucket.write(self.name, data if isinstance(data, str) else data.decode())

    def upload_from_filename(self, filename, content_type=None):
        self.bucket.write(self.name, Path(filename).read_text(encoding="utf-8"))

    def download_as_text(self) -> str:
        if self.name not in self.bucket.objects:
            raise NotFound(f"object {self.name} not found")
        return self.bucket.objects[self.name]

    def download_to_filename(self, filename) -> None:
        Path(filename).write_text(self.download_as_text(), encoding="utf-8")

    def delete(self, if_generation_match=None) -> None:
        if self.name not in self.bucket.objects:
            raise NotFound(f"object {self.name} not found")
        if if_generation_match is not None and if_generation_match != self.generation:
            raise PreconditionFailed(f"object {self.name} generation changed")
        del self.bucket.objects[self.name]
        del self.bucket.generations[self.name]


class FakeBucket:
    """In-memory objects: name -> text, plus a generation per write."""

    def __init__(self, name: str = "test-bucket"):
        self.name = name
        self.objects: dict[str, str] = {}
        self.generations: dict[str, int] = {}
        self._next_generation = 1

    def write(self, name: str, text: str) -> None:
        self.objects[name] = text
        self.generations[name] = self._next_generation
        self._next_generation += 1

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)

    def list_blobs(self, prefix: str = "", max_results: int | None = None):
        names = [name for name in sorted(self.objects) if name.startswith(prefix)]
        if max_results is not None:
            names = names[:max_results]
        return [FakeBlob(self, name) for name in names]
