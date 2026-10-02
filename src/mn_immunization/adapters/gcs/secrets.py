"""Google Cloud Secret Manager: a secret reader for one project."""

from __future__ import annotations

from collections.abc import Callable

import google.auth
from google.cloud import secretmanager


def secret_reader(project_id: str | None) -> Callable[[str], str]:
    """A secret name -> value reader for the district's project.

    The project is the configured one (GCP_PROJECT, passed in by the
    composition root) or, on Cloud Run, the one Application Default
    Credentials report — never a code default, so a misconfigured
    district fails loudly instead of silently reading another district's
    secrets. Resolution and the client are deferred to the first read.
    """
    resolved: dict[str, object] = {}

    def read(secret_name: str) -> str:
        if not resolved:
            project = project_id or google.auth.default()[1]
            if not project:
                raise RuntimeError(
                    "Cannot determine the GCP project for secret access: "
                    "set GCP_PROJECT or run with application default credentials"
                )
            resolved["project"] = project
            resolved["client"] = secretmanager.SecretManagerServiceClient()
        client = resolved["client"]
        name = f"projects/{resolved['project']}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})  # type: ignore[attr-defined]
        return response.payload.data.decode("UTF-8")

    return read
