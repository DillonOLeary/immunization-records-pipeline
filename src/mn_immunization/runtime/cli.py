"""Command-line interface: `mn-immunization status`.

The CLI is an operator's read-only window into the ledger. Everything
that changes state runs as the Cloud Run Job (`pipeline-job`);
manual operation is `gcloud run jobs execute`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

from mn_immunization.adapters.gcs.ledger import (
    CLAIMS_PREFIX,
    read_claims,
    read_recent_runs,
    recent_months,
)
from mn_immunization.adapters.gcs.storage import get_storage_client
from mn_immunization.workflow.events import TERMINAL_TYPES
from mn_immunization.workflow.history import History


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


def stuck_claims(bucket, now: datetime) -> list[tuple[str, dict]]:
    """Per-school query claims with no QuerySubmitted event, for every
    period the last two months of the ledger mention (and the current
    month's): (claim key, claimant payload). Each is a roster that may or
    may not have reached MIIC; runs skip it until a human decides. A run
    still submitting can show one here for a moment."""
    period_format = os.environ.get("QUERY_PERIOD_FORMAT", "%Y-%m")
    last_month = now.replace(day=1) - timedelta(days=1)
    periods = {now.strftime(period_format), last_month.strftime(period_format)}
    history = History.from_runs(
        read_recent_runs(bucket, recent_months(now, 2), limit=None)
    )
    periods |= history.periods()

    stuck = []
    for period in sorted(periods):
        prefix = f"{period}_query_"
        submitted = history.submissions(period)
        for key, payload in sorted(read_claims(bucket, prefix).items()):
            if key[len(prefix) :] not in submitted:
                stuck.append((key, payload))
    return stuck


def handle_status_command(args: argparse.Namespace) -> None:
    """Print recent runs and their terminal outcomes from the ledger, then
    any stuck roster claims."""
    # UTC: ledger folders are UTC months, and a UTC "now" is never behind a
    # US district's, so this month and last always cover its periods.
    now = datetime.now(UTC)
    bucket = get_storage_client().bucket(args.bucket)
    all_runs = read_recent_runs(bucket, recent_months(now, 2), limit=None)
    runs = all_runs[: args.limit]

    for period in History.from_runs(all_runs).open_periods():
        print(f"OPEN PERIOD {period.key} (opened {period.opened_at:%Y-%m-%dT%H:%M}Z)")
    if not runs:
        print("No runs found in the ledger for the last two months.")
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

    stuck = stuck_claims(bucket, now)
    if not stuck:
        return
    print()
    print("STUCK ROSTER CLAIMS (claimed, never recorded as submitted; runs skip")
    print("these schools until a human decides, see ONBOARDING: stuck claims):")
    for key, payload in stuck:
        holder = payload.get("run_id", "?")
        at = payload.get("at", "?")
        print(f"  {key}  claimed by {holder} at {at}")
        print("    if MIIC did NOT receive this roster (no nurse email), release it:")
        print(f"    gcloud storage rm gs://{args.bucket}/{CLAIMS_PREFIX}{key}")


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
