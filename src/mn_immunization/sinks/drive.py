"""Google Drive: the two Drive operations the pipeline performs.

Drive is the import queue and nothing else: files that district staff must
import into Infinite Campus land in one folder, and staff delete each file
after importing it as their own done-signal. Uploading fills the queue;
listing lets a later run notice which delivered files are gone and record
the import as confirmed.

The drive.file scope sees only files this app created, so a folder listing
returns exactly the pipeline's own deliveries — never anything else in the
district's Drive.
"""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _drive_service(refresh_token: str, client_id: str, client_secret: str):
    credentials = Credentials(
        token=None,  # refreshed automatically
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=DRIVE_SCOPES,
    )
    return build("drive", "v3", credentials=credentials)


def upload_to_google_drive(
    file_path: str,
    filename: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    folder_id: str = None,
) -> str:
    """Upload a file to Google Drive; returns the Drive file id."""
    from googleapiclient.http import MediaFileUpload

    service = _drive_service(refresh_token, client_id, client_secret)

    file_metadata = {"name": filename}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(file_path, resumable=True)
    file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id")
        .execute()
    )

    return file.get("id")


def list_drive_filenames(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    folder_id: str,
) -> set[str]:
    """Return the names of non-trashed files this app has in the folder.

    Absence is the signal: a delivered file that is no longer here was
    imported and deleted by staff.
    """
    service = _drive_service(refresh_token, client_id, client_secret)

    names: set[str] = set()
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
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
