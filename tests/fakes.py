"""Test doubles shared across the suite.

FakeBucket stands in for a google.cloud.storage Bucket at the surface the
pipeline's GCS adapters use. It honors the one semantic the claim
guarantee rests on, `if_generation_match=0` (create only if absent), and
raises the real NotFound / PreconditionFailed exceptions, so adapter code
under test takes its real error paths. `fail_next_write` injects one
failure into a named object's next write, to crash a run at an exact
point. FakeStorageClient wraps it as a client; FakeDrive records what was
delivered to the Drive folder.
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
        self.bucket.maybe_fail(self.name)
        if if_generation_match == 0 and self.name in self.bucket.objects:
            raise PreconditionFailed(f"object {self.name} already exists")
        self.bucket.write(self.name, data if isinstance(data, str) else data.decode())

    def upload_from_filename(self, filename, content_type=None):
        self.bucket.maybe_fail(self.name)
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
        self._failures: dict[str, Exception] = {}

    def fail_next_write(self, name: str, error: Exception) -> None:
        self._failures[name] = error

    def maybe_fail(self, name: str) -> None:
        error = self._failures.pop(name, None)
        if error is not None:
            raise error

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


class FakeStorageClient:
    """A storage.Client serving exactly one FakeBucket."""

    def __init__(self, bucket: FakeBucket):
        self._bucket = bucket

    def bucket(self, name: str) -> FakeBucket:
        assert name == self._bucket.name, f"unexpected bucket {name}"
        return self._bucket

    def list_blobs(self, bucket_name: str, prefix: str = "", max_results=None):
        return self.bucket(bucket_name).list_blobs(prefix, max_results)


class FakeDrive:
    """A DriveSink: the import queue, with what was uploaded and what is
    still there (staff delete a file once imported). `list_error` makes
    listing fail."""

    def __init__(self, list_error: Exception | None = None):
        self.files: dict[str, str] = {}
        self.uploads: list[str] = []
        self.list_error = list_error

    def upload(self, path: Path, name: str) -> str:
        self.files[name] = Path(path).read_text(encoding="utf-8")
        self.uploads.append(name)
        return f"drive-file-{len(self.uploads)}"

    def list_filenames(self) -> set[str]:
        if self.list_error is not None:
            raise self.list_error
        return set(self.files)
