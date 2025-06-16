"""
Google Cloud Storage helper functions for the immunization pipeline.
"""

import logging
from pathlib import Path
from typing import List

from google.cloud import storage

logger = logging.getLogger(__name__)


def get_storage_client() -> storage.Client:
    """Get Google Cloud Storage client."""
    return storage.Client()


def download_csv_files_from_gcs(bucket_name: str, prefix: str, local_dir: Path) -> List[Path]:
    """
    Download all CSV files from a GCS bucket prefix to a local directory.
    
    Args:
        bucket_name: Name of the GCS bucket
        prefix: Prefix to filter files (e.g., "input/")
        local_dir: Local directory to download files to
        
    Returns:
        List of downloaded file paths
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    
    local_dir.mkdir(parents=True, exist_ok=True)
    downloaded_files = []
    
    # List all CSV files with the given prefix
    blobs = bucket.list_blobs(prefix=prefix)
    csv_blobs = [blob for blob in blobs if blob.name.endswith('.csv')]
    
    for blob in csv_blobs:
        # Extract just the filename from the blob path
        filename = Path(blob.name).name
        local_path = local_dir / filename
        
        logger.info(f"Downloading gs://{bucket_name}/{blob.name} → {local_path}")
        blob.download_to_filename(local_path)
        downloaded_files.append(local_path)
    
    logger.info(f"Downloaded {len(downloaded_files)} CSV files from GCS")
    return downloaded_files


def upload_csv_files_to_gcs(bucket_name: str, local_dir: Path, gcs_prefix: str) -> List[str]:
    """
    Upload all CSV files from a local directory to a GCS bucket.
    
    Args:
        bucket_name: Name of the GCS bucket
        local_dir: Local directory containing files to upload
        gcs_prefix: Prefix for uploaded files (e.g., "output/")
        
    Returns:
        List of uploaded GCS blob names
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    
    uploaded_files = []
    csv_files = list(local_dir.glob("*.csv"))
    
    for local_file in csv_files:
        blob_name = f"{gcs_prefix}{local_file.name}"
        blob = bucket.blob(blob_name)
        
        logger.info(f"Uploading {local_file} → gs://{bucket_name}/{blob_name}")
        blob.upload_from_filename(local_file, content_type='text/csv')
        uploaded_files.append(blob_name)
    
    logger.info(f"Uploaded {len(uploaded_files)} CSV files to GCS")
    return uploaded_files


def upload_json_to_gcs(bucket_name: str, json_data: str, blob_name: str) -> str:
    """
    Upload JSON data to a GCS bucket.
    
    Args:
        bucket_name: Name of the GCS bucket
        json_data: JSON string to upload
        blob_name: Name for the blob in GCS
        
    Returns:
        The uploaded blob name
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    logger.info(f"Uploading JSON data → gs://{bucket_name}/{blob_name}")
    blob.upload_from_string(json_data, content_type='application/json')
    
    return blob_name


def download_json_from_gcs(bucket_name: str, blob_name: str) -> str:
    """
    Download JSON data from a GCS bucket.
    
    Args:
        bucket_name: Name of the GCS bucket
        blob_name: Name of the blob to download
        
    Returns:
        JSON string content
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    logger.info(f"Downloading JSON from gs://{bucket_name}/{blob_name}")
    content = blob.download_as_text()
    
    return content


def list_csv_files_in_gcs(bucket_name: str, prefix: str) -> List[str]:
    """
    List all CSV files in a GCS bucket with a given prefix.
    
    Args:
        bucket_name: Name of the GCS bucket
        prefix: Prefix to filter files
        
    Returns:
        List of CSV file blob names
    """
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    
    blobs = bucket.list_blobs(prefix=prefix)
    csv_files = [blob.name for blob in blobs if blob.name.endswith('.csv')]
    
    logger.info(f"Found {len(csv_files)} CSV files in gs://{bucket_name}/{prefix}")
    return csv_files