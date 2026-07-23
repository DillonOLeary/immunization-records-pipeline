"""Command-line interface: `mn-immunization status`.

The CLI is an operator's read-only window into the ledger. Everything
that changes state runs as the Cloud Run Job (`mn-immunization-job`);
manual operation is `gcloud run jobs execute`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from mn_immunization.gcp.storage import get_storage_client
from mn_immunization.ledger.events import TERMINAL_TYPES
from mn_immunization.ledger.gcs_ledger import read_recent_runs


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minnesota Immunization Data Pipeline for school districts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser(
        "status", help="Show recent pipeline runs from the ledger"
    )
    status_parser.add_argument(
        "--bucket", type=str, required=True, help="GCS bucket holding the ledger"
    )
    status_parser.add_argument(
        "--limit", type=int, default=10, help="Number of runs to show (default 10)"
    )
    return parser


def handle_status_command(args: argparse.Namespace) -> None:
    """Print recent runs and their terminal outcomes from the ledger."""
    now = datetime.now()
    previous = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    months = ((now.year, now.month), previous)

    bucket = get_storage_client().bucket(args.bucket)
    runs = read_recent_runs(bucket, months, limit=args.limit)

    if not runs:
        print("No runs found in the ledger for the last two months.")
        return

    for run in runs:
        first, last = run["events"][0], run["events"][-1]
        if last["type"] in TERMINAL_TYPES:
            outcome = last["type"]
            detail = ", ".join(f"{k}={v}" for k, v in last["data"].items())
        else:
            outcome = "NO TERMINAL EVENT"
            detail = f"last event: {last['type']}"
        print(f"{first['at']}  {run['run_id']}")
        print(f"    {outcome}  {detail}")


COMMANDS = {"status": handle_status_command}


def main(argv: list[str] | None = None) -> int:
    # stdout on purpose: Cloud Run ingests stderr with ERROR severity, and
    # routine info lines must not read as errors in Cloud Logging.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stdout,
    )
    args = create_parser().parse_args(argv)
    COMMANDS[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
