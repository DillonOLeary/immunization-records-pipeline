"""Cloud Run Job entrypoint.

One container, four cycles: `mn-immunization-job run|tick|canary|refresh`.
Cloud Scheduler executes `run` on the district's cadence (it opens a
period), `tick` every few hours (it advances the open one), and `canary`
the day before a run. A human retries a closed period with `gcloud run
jobs execute pipeline-job --args=run,--trigger,manual` (safe: ledger
claims prevent duplicate emails and deliveries). `canary` is a read-only
readiness probe; `refresh` rebuilds the known set from MIIC and
delivers all of it (idempotent on the IC side).

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

from mn_immunization.runtime.advice import advise
from mn_immunization.runtime.composition import build_services
from mn_immunization.workflow.cycles import (
    run_canary_cycle,
    run_cycle,
    run_refresh_cycle,
    run_tick_cycle,
)
from mn_immunization.workflow.services import Services
from mn_immunization.workflow.settings import Settings, SettingsError

CYCLES = {
    "run": run_cycle,
    "tick": run_tick_cycle,
    "canary": run_canary_cycle,
    "refresh": run_refresh_cycle,
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
        _report(
            {"status": "failed", "step": "startup", "error": "SettingsError"},
            headline="The job's configuration is invalid",
            what_to_do=f"{error.variable} {error.problem}. Fix it in "
            "infra/modules/district/job.tf (or the execution's overrides).",
        )
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
    # waiting: the period continues on the next tick; idle: none is open.
    ok = ("success", "skipped", "waiting", "idle")
    if result.get("status") in ok:
        print(json.dumps(result))
        return 0
    headline, what_to_do = advise(result, settings.data_bucket)
    also = result.get("failed_checks", [])[1:]
    if also:
        what_to_do += f" Also failing: {', '.join(also)}."
    _report(result, headline, what_to_do)
    return 1


def _report(result: dict, headline: str, what_to_do: str) -> None:
    """The one line a failure prints. Cloud Logging reads `severity` and
    `message` from it; the action-needed alert (infra alerts.tf) emails
    `action_needed` as the subject and `what_to_do` as the body."""
    print(
        json.dumps(
            {
                **result,
                "severity": "ERROR",
                "message": headline,
                "action_needed": headline,
                "what_to_do": what_to_do,
            }
        )
    )


def where(error: BaseException, depth: int = 6) -> list[str]:
    """The innermost traceback frames as `file:line in function`, with no
    message and no local values: enough to find the failure in code."""
    frames = traceback.extract_tb(error.__traceback__)[-depth:]
    return [f"{Path(f.filename).name}:{f.lineno} in {f.name}" for f in frames]


if __name__ == "__main__":
    sys.exit(main())
