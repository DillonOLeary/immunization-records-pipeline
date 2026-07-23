"""Cloud Run Job entrypoint.

One container, two cycles: `mn-immunization-job run|canary`. Cloud
Scheduler executes `run` on the configured cadence; a human reruns it with
`gcloud run jobs execute pipeline-job --args=run,--trigger,manual` (safe:
ledger claims prevent duplicate emails and deliveries). `canary` is a
read-only readiness probe.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from mn_immunization.runtime.cycles import run_canary_cycle, run_cycle

CYCLES = {
    "run": run_cycle,
    "canary": run_canary_cycle,
}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Run one pipeline cycle.")
    parser.add_argument("cycle", choices=sorted(CYCLES))
    parser.add_argument(
        "--trigger",
        choices=["scheduled", "manual"],
        default=os.environ.get("TRIGGER", "scheduled"),
    )
    args = parser.parse_args(argv)

    bucket_name = os.environ.get("DATA_BUCKET")
    if not bucket_name:
        print("DATA_BUCKET is not set", file=sys.stderr)
        return 2

    result = CYCLES[args.cycle](bucket_name, trigger=args.trigger)
    print(json.dumps(result))
    return 0 if result.get("status") in ("success", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
