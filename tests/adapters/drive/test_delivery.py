"""The Drive adapter against a fake Drive service: exactly what it asks
Google to do. The pipeline's other tests use a fake Delivery, so these
are the only ones that see the real adapter's requests."""

from mn_immunization.adapters.drive import delivery as drive

SECRETS = {
    "drive-refresh-token": "r",
    "drive-client-id": "c",
    "drive-client-secret": "s",
}


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeFiles:
    def __init__(self, pages=None):
        self.created, self.listed = [], []
        self.pages = pages or [{"files": []}]

    def create(self, body, media_body, fields):
        self.created.append((body, media_body))
        return Request({"id": "file-1"})

    def list(self, **query):
        self.listed.append(query)
        return Request(self.pages[len(self.listed) - 1])


def delivery(monkeypatch, files):
    service = type("Service", (), {"files": lambda self: files})()
    monkeypatch.setattr(drive, "build", lambda *args, **kwargs: service)
    return drive.GoogleDriveDelivery("folder-1", SECRETS.__getitem__)


def test_upload_puts_the_text_into_the_configured_folder(monkeypatch):
    files = FakeFiles()
    name = "2026-10-13_0217_new_01-of-01.csv"

    assert delivery(monkeypatch, files).upload(name, "1,2,MMR,01/01/2020\n") == "file-1"

    ((body, media),) = files.created
    assert body == {"name": name, "parents": ["folder-1"]}
    assert media.mimetype() == "text/csv"
    assert media.getbytes(0, 100) == b"1,2,MMR,01/01/2020\n"


def test_listing_reads_every_page_of_just_that_folder(monkeypatch):
    files = FakeFiles(
        pages=[
            {"files": [{"name": "a.csv"}], "nextPageToken": "p2"},
            {"files": [{"name": "b.csv"}]},
        ]
    )

    assert delivery(monkeypatch, files).list_filenames() == {"a.csv", "b.csv"}

    assert files.listed[0]["q"] == "'folder-1' in parents and trashed = false"
    assert files.listed[1]["pageToken"] == "p2"
