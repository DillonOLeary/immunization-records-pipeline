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

    return file.get("id")


def find_or_create_school_folder(
    service, school_name: str, parent_folder_id: str = None
) -> str:
    """
    Find or create a school folder in Google Drive

    Args:
        service: Google Drive API service instance
        school_name: Name of the school to create/find folder for
        parent_folder_id: Optional parent folder ID

    Returns:
        Google Drive folder ID
    """
    try:
        # Clean up school name for folder name (remove special characters)
        folder_name = school_name.replace("/", "-").replace("\\", "-").strip()

        # Search for existing folder
        query = (
            f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
        )
        if parent_folder_id:
            query += f" and '{parent_folder_id}' in parents"

        results = service.files().list(q=query, fields="files(id, name)").execute()

        folders = results.get("files", [])

        # If folder exists, return its ID
        if folders:
            return folders[0]["id"]

        # Create new folder
        folder_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }

        if parent_folder_id:
            folder_metadata["parents"] = [parent_folder_id]

        folder = service.files().create(body=folder_metadata, fields="id").execute()

        folder_id = folder.get("id")
        print(f"Created Google Drive folder '{folder_name}' with ID: {folder_id}")
        return folder_id

    except Exception as e:
        print(f"WARNING: Failed to create/find folder '{school_name}': {e}")
        # Return parent folder ID or None as fallback
        return parent_folder_id


def upload_to_school_folder(
    file_path: str,
    filename: str,
    school_name: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    parent_folder_id: str = None,
) -> str:
    """
    Upload file to a school-specific folder in Google Drive

    Args:
        file_path: Path to the file to upload
        filename: Name to give the file in Google Drive
        school_name: Name of the school (used for folder organization)
        refresh_token: OAuth refresh token
        client_id: OAuth client ID
        client_secret: OAuth client secret
        parent_folder_id: Optional parent folder ID

    Returns:
        Google Drive file ID of uploaded file
    """
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )

    service = build("drive", "v3", credentials=credentials)

    # Find or create school-specific folder
    school_folder_id = find_or_create_school_folder(
        service, school_name, parent_folder_id
    )

    # Upload file to school folder
    return upload_to_google_drive(
        file_path=file_path,
        filename=filename,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        folder_id=school_folder_id,
    )
