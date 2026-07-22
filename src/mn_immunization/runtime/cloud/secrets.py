"""
Google Cloud Secret Manager utilities
"""

import os

from google.cloud import secretmanager


def get_secret(secret_name: str) -> str:
    """
    Retrieve secret from Google Cloud Secret Manager

    Args:
        secret_name: Name of the secret to retrieve

    Returns:
        Secret value as string
    """
    client = secretmanager.SecretManagerServiceClient()
    project_id = os.environ.get("GCP_PROJECT", "mn-immun-bd9001")
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"

    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")
