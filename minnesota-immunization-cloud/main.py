"""
Cloud Functions entry point for Terraform deployment
Re-exports functions from the proper package structure
"""

from minnesota_immunization_cloud.main import download_handler, upload_handler

# Re-export for Terraform compatibility
__all__ = ["upload_handler", "download_handler"]