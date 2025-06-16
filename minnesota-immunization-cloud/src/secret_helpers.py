"""
Google Secret Manager helper functions for the immunization pipeline.
"""

import logging
import os

from google.cloud import secretmanager

logger = logging.getLogger(__name__)


def get_secret(secret_name: str, project_id: str = None) -> str:
    """
    Get secret from Google Secret Manager.
    
    Args:
        secret_name: Name of the secret
        project_id: GCP project ID (defaults to GCP_PROJECT env var)
        
    Returns:
        Secret value as string
        
    Raises:
        Exception: If secret cannot be retrieved
    """
    if project_id is None:
        project_id = os.environ.get('GCP_PROJECT')
        if not project_id:
            raise ValueError("Project ID must be provided or set in GCP_PROJECT env var")
    
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        
        logger.info(f"Successfully retrieved secret: {secret_name}")
        return secret_value
        
    except Exception as e:
        logger.error(f"Failed to get secret {secret_name}: {e}")
        raise


def get_aisr_credentials(project_id: str = None) -> tuple[str, str]:
    """
    Get AISR username and password from Secret Manager.
    
    Args:
        project_id: GCP project ID (defaults to GCP_PROJECT env var)
        
    Returns:
        Tuple of (username, password)
    """
    username = get_secret("aisr-username", project_id)
    password = get_secret("aisr-password", project_id)
    
    return username, password