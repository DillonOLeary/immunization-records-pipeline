"""Staging: has MDH turned this period's rosters into results yet?

The one step that waits on someone else's clock. `probe_staging` lists
each school's results read-only; the executor counts only results
uploaded since that school's submission this period, because AISR keeps
the previous period's results listed for days.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from mn_immunization.workflow.context import RunContext
from mn_immunization.workflow.ports import Registry, School
from mn_immunization.workflow.steps.submit import query_period, submission_times

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StagingProbe:
    staged: int  # schools whose latest listed entry has a results file
    failed: int  # schools whose listing call failed


# Allowance for clock skew between our ledger stamps and MDH's upload time.
# Stale results are days old, so ten minutes cannot mistake one for fresh.
FRESHNESS_SKEW = timedelta(minutes=10)


def probe_staging(
    registry: Registry,
    schools: list[School],
    now: datetime,
    submitted_at: dict[str, datetime] | None = None,
) -> StagingProbe:
    """Read-only listing of every school's results.

    AISR keeps a school's previous results listed for days after a run
    (seen in production 2026-10-01: a rerun's first probe found every
    school "staged" with three-day-old files). So when `submitted_at`
    gives a school's submission time this period, its results count as
    staged only if they were uploaded no earlier than that (less
    FRESHNESS_SKEW); older ones are last period's and the probe keeps
    waiting. Without a submission time (the canary), anything listed
    counts.

    A school whose listing fails is counted in `failed` and logged by
    error class; it never aborts the others.
    """
    now_utc = now.astimezone(UTC)
    staged = failed = 0
    for school in schools:
        try:
            results = registry.staged_results(school.id)
        except Exception as error:
            failed += 1
            logger.warning(
                "Staging check failed for %s: %s",
                school.name,
                type(error).__name__,
            )
            continue
        newest = results.newest_upload_at
        since = (submitted_at or {}).get(school.id)
        fresh = since is None or (
            newest is not None and newest >= since - FRESHNESS_SKEW
        )
        logger.info(
            "Results listing for %s: %d entries, newest upload %s, staged=%s",
            school.name,
            results.entries,
            f"{(now_utc - newest).days}d ago" if newest else "undated",
            results.available and fresh,
        )
        if results.available and fresh:
            staged += 1
    return StagingProbe(staged=staged, failed=failed)


def probe_staged(ctx: RunContext, school_ids: frozenset[str]) -> int:
    """Staged count among the schools submitted this period, counting only
    results uploaded since each school's submission; the others are not
    waited for."""
    schools = [school for school in ctx.schools if school.id in school_ids]
    since = submission_times(ctx.ledger.recent_runs(), query_period(ctx))
    with ctx.open_registry() as registry:
        probe = probe_staging(registry, schools, ctx.clock.now(), since)
    logger.info("%d/%d schools have results staged", probe.staged, len(schools))
    return probe.staged
