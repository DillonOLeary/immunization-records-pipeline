"""Google Drive: the DriveSink the pipeline delivers to.

Drive is the import queue and nothing else: files that district staff must
import into Infinite Campus land in one folder, and staff delete each file
after importing it as their own done-signal. Uploading fills the queue;
listing lets a later run notice which delivered files are gone and record
the import as confirmed.

The drive.file scope sees only files this app created, so a folder listing
returns exactly the pipeline's own deliveries — never anything else in the
district's Drive.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GoogleDriveSink:
    """DriveSink bound to one folder. OAuth credentials come from `secret`
    (a secret name -> value reader) when a call needs them, so nothing
    outside this adapter ever holds them."""

    def __init__(self, folder_id: str, secret: Callable[[str], str]) -> None:
        self.folder_id = folder_id
        self._secret = secret

    def _service(self):
        credentials = Credentials(
            token=None,  # refreshed automatically
            refresh_token=self._secret("drive-refresh-token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._secret("drive-client-id"),
            client_secret=self._secret("drive-client-secret"),
            scopes=DRIVE_SCOPES,
        )
        return build("drive", "v3", credentials=credentials)

    def upload(self, path: Path, name: str) -> str:
        """Upload a file into the folder; returns the Drive file id."""
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(str(path), resumable=True)
        file = (
            self._service()
            .files()
            .create(
                body={"name": name, "parents": [self.folder_id]},
                media_body=media,
                fields="id",
            )
            .execute()
        )
        return file.get("id")

    def list_filenames(self) -> set[str]:
        """Names of the non-trashed files this app has in the folder.

        Absence is the signal: a delivered file that is no longer here was
        imported and deleted by staff.
        """
        service = self._service()
        names: set[str] = set()
        page_token = None
        while True:
            response = (
                service.files()
                .list(
                    q=f"'{self.folder_id}' in parents and trashed = false",
                    spaces="drive",
                    fields="nextPageToken, files(name)",
                    pageToken=page_token,
                )
                .execute()
            )
            names.update(f["name"] for f in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return names
