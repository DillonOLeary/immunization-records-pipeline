"""
Google Cloud Secret Manager utilities
"""

import os

import google.auth
from google.cloud import secretmanager


def get_secret(secret_name: str) -> str:
    """
    Retrieve secret from Google Cloud Secret Manager

    The project comes from GCP_PROJECT or, on Cloud Run, from the
    metadata server via ADC — never from a code default, so a
    misconfigured district fails loudly instead of silently reading
    another district's secrets.

    Args:
        secret_name: Name of the secret to retrieve

    Returns:
        Secret value as string
    """
    project_id = os.environ.get("GCP_PROJECT")
    if not project_id:
        _, project_id = google.auth.default()
    if not project_id:
        raise RuntimeError(
            "Cannot determine the GCP project for secret access: "
            "set GCP_PROJECT or run with application default credentials"
        )
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"

    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")
