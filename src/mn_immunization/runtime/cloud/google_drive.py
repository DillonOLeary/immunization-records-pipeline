"""Google Drive upload: the one Drive operation the pipeline performs.

Drive is the import queue and nothing else: files that district staff must
import into Infinite Campus land in one folder, and staff delete each file
after importing it as their own done-signal.
"""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def upload_to_google_drive(
    file_path: str,
    filename: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    folder_id: str = None,
) -> str:
    """Upload a file to Google Drive; returns the Drive file id."""
    credentials = Credentials(
        token=None,  # refreshed automatically
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )

    service = build("drive", "v3", credentials=credentials)

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
