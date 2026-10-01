"""Cloud Run Job entrypoint.

One container, three cycles: `mn-immunization-job run|canary|rebaseline`.
Cloud Scheduler executes `run` and `canary` on the configured cadences; a
human reruns with `gcloud run jobs execute pipeline-job
--args=run,--trigger,manual` (safe: ledger claims prevent duplicate
emails and deliveries). `canary` is a read-only readiness probe;
`rebaseline` pushes the whole known set to Drive in chunks to recover
from sync trouble (idempotent on the IC side).

This is where the environment is read (once, into Settings) and where
the adapters are built (runtime/composition.py); everything below
receives them.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path

from mn_immunization.pipeline.cycles import (
    run_canary_cycle,
    run_cycle,
    run_rebaseline_cycle,
)
from mn_immunization.pipeline.services import Services
from mn_immunization.pipeline.settings import Settings, SettingsError
from mn_immunization.runtime.composition import build_services

CYCLES = {
    "run": run_cycle,
    "canary": run_canary_cycle,
    "rebaseline": run_rebaseline_cycle,
}


def main(
    argv: list[str] | None = None,
    env: Mapping[str, str] = os.environ,
    build: Callable[[Settings], Services] = build_services,
) -> int:
    # stdout on purpose: Cloud Run ingests stderr with ERROR severity, and
    # routine info lines must not read as errors in Cloud Logging.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(description="Run one pipeline cycle.")
    parser.add_argument("cycle", choices=sorted(CYCLES))
    parser.add_argument(
        "--trigger",
        choices=["scheduled", "manual"],
        default=env.get("TRIGGER", "scheduled"),
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env(env)
    except SettingsError as error:
        print(f"configuration error: {error.variable} {error.problem}", file=sys.stderr)
        return 2

    try:
        result = CYCLES[args.cycle](build(settings), trigger=args.trigger)
    except Exception as error:
        # An uncaught exception would print a traceback whose last line is
        # the exception message, and messages can carry response bodies or
        # field values. Print the class and where it happened, never the
        # message; the cycle has already recorded RunFailed in the ledger.
        result = {
            "status": "failed",
            "error": type(error).__name__,
            "where": where(error),
        }
    print(json.dumps(result))
    return 0 if result.get("status") in ("success", "skipped") else 1


def where(error: BaseException, depth: int = 6) -> list[str]:
    """The innermost traceback frames as `file:line in function`, with no
    message and no local values: enough to find the failure in code."""
    frames = traceback.extract_tb(error.__traceback__)[-depth:]
    return [f"{Path(f.filename).name}:{f.lineno} in {f.name}" for f in frames]


if __name__ == "__main__":
    sys.exit(main())
