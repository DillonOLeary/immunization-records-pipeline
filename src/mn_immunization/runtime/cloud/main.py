"""Legacy Cloud Function entrypoints.

Thin wrappers over the shared run cycles; the Cloud Run Job and the CLI run
the same cycle functions. These handlers exist until the phase 5 cutover,
then get deleted along with their Pub/Sub plumbing.
"""

import os

from mn_immunization.runtime.cycles import run_download_cycle, run_query_cycle


def upload_handler(event, context):
    """Pub/Sub-triggered: submit bulk roster queries to AISR."""
    return run_query_cycle(os.environ["DATA_BUCKET"], trigger="scheduled")


def download_handler(event, context):
    """Pub/Sub-triggered: download, transform, diff, and deliver."""
    return run_download_cycle(os.environ["DATA_BUCKET"], trigger="scheduled")
