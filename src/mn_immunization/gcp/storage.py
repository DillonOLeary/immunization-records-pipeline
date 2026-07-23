"""
Google Cloud Storage utilities for file operations
"""

from google.cloud import storage


def get_storage_client() -> storage.Client:
    """Get Google Cloud Storage client"""
    return storage.Client()


def upload_file_to_storage(bucket_name: str, blob_name: str, file_path: str) -> None:
    """
    Upload file to Google Cloud Storage

    Args:
        bucket_name: Name of the GCS bucket
        blob_name: Name of the blob (file path) in the bucket
        file_path: Local path to the file to upload
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(file_path)


def download_from_storage(
    bucket_name: str, blob_name: str, destination_path: str
) -> None:
    """
    Download file from Google Cloud Storage

    Args:
        bucket_name: Name of the GCS bucket
        blob_name: Name of the blob (file path) in the bucket
        destination_path: Local path where file should be saved
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(destination_path)
