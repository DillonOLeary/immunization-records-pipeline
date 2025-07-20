"""
Google Drive integration for uploading files
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
    """
    Upload file to Google Drive using OAuth credentials

    Args:
        file_path: Path to the file to upload
        filename: Name to give the file in Google Drive
        refresh_token: OAuth refresh token
        client_id: OAuth client ID
        client_secret: OAuth client secret
        folder_id: Optional Google Drive folder ID to upload to

    Returns:
        Google Drive file ID of uploaded file

    Raises:
        Exception: If upload fails
    """
    credentials = Credentials(
        token=None,  # Will be refreshed automatically
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

    file_id = file.get("id")
    print(f"Uploaded {filename} to Google Drive with ID: {file_id}")
    return file_id
