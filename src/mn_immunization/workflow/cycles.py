"""The pipeline's use-cases.

A period is the pipeline's unit of work: one roster submission per
school, then results, a diff, a delivery, and a master commit.
`run_cycle` opens a period (on the district's cadence) and
`run_tick_cycle` (every few hours) advances whichever period is open;
both hand it to `runner.run_to_completion`, where `policy.decide` names
each next step. Waiting for MDH to stage results ends an execution
rather than sleeping in it, so a period spans as many executions as it
needs. Claims in the ledger make every execution safe to repeat: no
school's roster goes out twice in a period (each one emails every
nurse), and no diff is delivered twice.

`run_canary_cycle` is a read-only probe (login + staged-results count).
`run_refresh_cycle` rebuilds the known set from MIIC and delivers all of
it; safe any time because IC imports are idempotent.

Each cycle owns its ledger and guarantees a terminal event; an idle tick
writes nothing at all.
"""

from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path

from mn_immunization.workflow import events
from mn_immunization.workflow.context import RunContext
from mn_immunization.workflow.history import History
from mn_immunization.workflow.known import commit_known as write_known
from mn_immunization.workflow.known import load_known_records
from mn_immunization.workflow.periods import OpenPeriod, period_key
from mn_immunization.workflow.ports import RunLedger
from mn_immunization.workflow.runner import run_to_completion
from mn_immunization.workflow.services import Services
from mn_immunization.workflow.steps.delivery import (
    deliver_records,
    record_import_confirmations,
)
from mn_immunization.workflow.steps.diff import fetch_all
from mn_immunization.workflow.steps.staging import probe_staging
from mn_immunization.workflow.steps.submit import query_period
from mn_immunization.workflow.support import append_event, new_run_id

logger = logging.getLogger(__name__)


@contextmanager
def pipeline_run(
    kind: str,
    services: Services,
    trigger: str,
    *,
    ledger: RunLedger | None = None,
    period: OpenPeriod | None = None,
):
    """Common cycle scaffolding: the run's ledger, config, schools, temp
    dir, the period it works on (`period`, or the one a submission made
    now would belong to), and the guarantee that an escaping exception is
    recorded as RunFailed. For `run` and `tick`, which work on the period,
    it also closes the period, as every other failure does: one alert,
    not one per tick."""
    now = services.clock.now()
    ledger = ledger or services.new_ledger(new_run_id(kind, now))
    append_event(ledger, events.run_started(kind=kind, trigger=trigger))
    if period is None:
        settings = services.settings
        local = now.astimezone(settings.time_zone)
        period = OpenPeriod(period_key(local, settings.query_period_format), now)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            district = services.load_district()
            schools = list(district.schools)
            logger.info(
                "Loaded configuration for %d schools: %s",
                len(schools),
                ", ".join(s.name for s in schools),
            )
            yield RunContext(
                settings=services.settings,
                clock=services.clock,
                ledger=ledger,
                objects=services.objects,
                delivery=services.delivery,
                open_registry=district.open_registry,
                temp=Path(temp_dir),
                period=period.key,
                opened_at=period.opened_at,
                schools=schools,
            )
    except Exception as error:
        if kind in ("run", "tick"):
            append_event(ledger, events.period_closed(period.key, "failed"))
        append_event(
            ledger,
            events.run_failed(step=f"{kind}_cycle", error=type(error).__name__),
        )
        raise


def run_cycle(services: Services, trigger: str = "scheduled") -> dict:
    """Open this period, or reopen it, and advance it as far as it goes now.

    Reopening is how a human retries a closed period: rosters already
    submitted this period are never sent again, and the staging deadline
    starts over. Any other period still open is closed as superseded:
    AISR lists only each school's latest results, so a new submission
    makes the old period's unreachable, and the new results (each
    student's full history) carry everything the old ones would have.

    First, reconcile the Drive import queue: files staff have deleted
    (imported) since get an ImportConfirmed event. Best-effort; it never
    blocks the delivery work.
    """
    with pipeline_run("run", services, trigger) as ctx:
        for other in ctx.history().open_periods():
            if other.key != ctx.period:
                append_event(ctx.ledger, events.period_closed(other.key, "superseded"))
        append_event(ctx.ledger, events.period_opened(ctx.period))
        record_import_confirmations(ctx)
        return run_to_completion(ctx)


def run_tick_cycle(services: Services, trigger: str = "scheduled") -> dict:
    """Advance the open period, if there is one: probe staging and, once
    results are in (or the deadline has passed), diff, deliver, commit.

    With no period open, write nothing at all: most ticks are idle, and
    the ledger records work, not polling."""
    ledger = services.new_ledger(new_run_id("tick", services.clock.now()))
    periods = History.from_runs(ledger.recent_runs()).open_periods()
    if not periods:
        logger.info("No open period; nothing to do")
        return {"status": "idle"}
    newest = periods[0]
    with pipeline_run("tick", services, trigger, ledger=ledger, period=newest) as ctx:
        record_import_confirmations(ctx)
        return run_to_completion(ctx)


def run_refresh_cycle(services: Services, trigger: str = "manual") -> dict:
    """Rebuild the known set from MIIC and deliver all of it.

    Fetches every school's latest results (no roster goes out, so no one
    is emailed), delivers every record as capped `refresh` files, then
    replaces the known set with exactly those records. Safe any time,
    because Infinite Campus imports are idempotent; it is also how a lost
    or cleared cache is rebuilt. All or nothing: if any school's results
    cannot be fetched, nothing is delivered or replaced.
    """
    with pipeline_run("refresh", services, trigger) as ctx:
        if ctx.delivery is None:
            append_event(
                ctx.ledger, events.run_failed(step="refresh", error="NoDriveFolder")
            )
            return {"status": "failed", "reason": "GOOGLE_DRIVE_FOLDER_ID not set"}

        records, _, failures = fetch_all(ctx)
        if failures or not records:
            error = "FetchFailed" if failures else "NoRecords"
            append_event(ctx.ledger, events.run_failed(step="refresh", error=error))
            return {
                "status": "failed",
                "reason": f"{failures} school(s) failed to fetch"
                if failures
                else "MIIC listed no records",
            }

        _, files = deliver_records(ctx, records, "refresh")
        write_known(ctx.objects, records, ctx.ledger)
        append_event(
            ctx.ledger, events.run_completed(files=files, records=len(records))
        )
        logger.info("Refresh complete: %d records in %d files", len(records), files)
        return {"status": "success", "files": files, "records": len(records)}


def run_canary_cycle(services: Services, trigger: str = "scheduled") -> dict:
    """Read-only readiness probe: AISR login plus a staged-results count per
    school, and a full read of the known-vaccinations master, so that an
    unreadable master (MasterMissingError, a malformed row) fails here, a day
    before the run. Moves no PHI and sends no email: the master is read
    in memory, and only counts are logged or recorded."""
    with pipeline_run("canary", services, trigger) as ctx:
        logger.info(
            "District zone %s: roster period %s",
            ctx.settings.time_zone.key,
            query_period(ctx),
        )
        with ctx.open_registry() as registry:
            probe = probe_staging(registry, ctx.schools, ctx.clock.now())
        available = probe.staged
        if probe.failed:
            # The run cycle tolerates a failed listing (it retries for
            # hours); the canary exists to notice one, so it fails loudly.
            append_event(
                ctx.ledger,
                events.run_failed(step="canary", error="StagingCheckFailed"),
            )
            logger.error(
                "Canary failed: results listing failed for %d/%d schools",
                probe.failed,
                len(ctx.schools),
            )
            return {
                "status": "failed",
                "reason": f"results listing failed for {probe.failed} school(s)",
            }
        known = load_known_records(ctx.objects)

        append_event(
            ctx.ledger,
            events.run_completed(
                schools_checked=len(ctx.schools),
                records_available=available,
                known_records=len(known),
            ),
        )
        logger.info(
            "Canary passed: login ok, %d/%d schools have records available, "
            "master readable with %d known records",
            available,
            len(ctx.schools),
            len(known),
        )
        return {
            "status": "success",
            "schools_checked": len(ctx.schools),
            "records_available": available,
            "known_records": len(known),
        }
