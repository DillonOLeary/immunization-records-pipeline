"""Cloud Run Job entrypoint.

One container, three cycles: `mn-immunization-job query|download|canary`.
Cloud Scheduler executes the job with the cycle as an argument; a human
runs `gcloud run jobs execute pipeline-job --args=download,--trigger,manual`
and the manual trigger is recorded in the ledger.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from mn_immunization.runtime.cycles import (
    run_canary_cycle,
    run_download_cycle,
    run_query_cycle,
)

CYCLES = {
    "query": run_query_cycle,
    "download": run_download_cycle,
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
