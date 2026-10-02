"""Fetch every school's latest results, diff them against the known set,
and (after delivery) commit the known set forward."""

from __future__ import annotations

import logging

from mn_immunization.records.model import RecordSet
from mn_immunization.workflow import events
from mn_immunization.workflow.context import RunContext
from mn_immunization.workflow.known import commit_known as write_known
from mn_immunization.workflow.known import diff_against_known
from mn_immunization.workflow.policy import DiffResult
from mn_immunization.workflow.support import append_event

logger = logging.getLogger(__name__)


def fetch_all(ctx: RunContext) -> tuple[RecordSet, int, int]:
    """Every school's latest results, unioned: (records, schools fetched,
    schools failed). One school's failure (after retries) is counted and
    logged by class, never fatal to the others."""
    current = RecordSet()
    fetched = failures = 0
    with ctx.open_registry() as registry:
        for school in ctx.schools:
            try:
                result = registry.fetch_latest_records(school.id)
            except Exception as error:
                # Not listed, not downloadable, or not parseable. All of
                # them failing is AllDownloadsFailed, which is where a
                # MIIC format change lands.
                failures += 1
                logger.error(
                    "Fetch failed for %s: %s (HTTP %s)",
                    school.name,
                    type(error).__name__,
                    getattr(error, "status_code", None),
                )
                continue
            fetched += 1
            append_event(
                ctx.ledger,
                events.records_fetched(
                    school_id=school.id,
                    content_hash=result.content_hash,
                    byte_size=result.byte_size,
                ),
            )
            current = current.union(result.records)
            logger.info("Fetched %d records for %s", len(result.records), school.name)
    return current, fetched, failures


def fetch_and_diff(ctx: RunContext) -> DiffResult:
    """Fetch and diff against the known set. Reads only: nothing here needs
    unwinding if the brake fires next."""
    current, fetched, failures = fetch_all(ctx)
    new, known_after, known_count = diff_against_known(current, ctx.objects, ctx.ledger)
    return DiffResult(
        new_count=len(new),
        known_count=known_count,
        files_transformed=fetched,
        fetch_failures=failures,
        new_records=new,
        known_after=known_after,
    )


def commit_known(ctx: RunContext, diff: DiffResult) -> None:
    write_known(ctx.objects, diff.known_after, ctx.ledger)
