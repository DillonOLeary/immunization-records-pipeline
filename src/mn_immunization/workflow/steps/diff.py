"""Fetch every school's latest results, diff them against the known set,
and (after delivery) commit the known set forward."""

from __future__ import annotations

import logging

from mn_immunization.records.model import RecordSet
from mn_immunization.workflow import events
from mn_immunization.workflow.context import RunContext
from mn_immunization.workflow.known import commit_master, compute_diff
from mn_immunization.workflow.policy import DiffResult
from mn_immunization.workflow.support import append_event

logger = logging.getLogger(__name__)


def fetch_and_diff(ctx: RunContext) -> DiffResult:
    """Fetch every school's latest results and diff them against the known
    set. Reads only: nothing this executor does needs unwinding if the
    brake fires next."""
    current = RecordSet()
    fetched = fetch_failures = 0
    with ctx.open_registry() as registry:
        for school in ctx.schools:
            try:
                result = registry.fetch_latest_records(school.id)
            except Exception as error:
                # Not listed, not downloadable, or not parseable: one
                # school's loss (after retries) is counted, never fatal to
                # the others. All of them failing is AllDownloadsFailed,
                # which is where a MIIC format change lands.
                fetch_failures += 1
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

    diff_path, master_path, new_count, known_count = compute_diff(
        current=current,
        output_folder=ctx.temp,
        objects=ctx.objects,
        snapshots=ctx.snapshots,
        ledger=ctx.ledger,
        now=ctx.local_now(),
    )
    logger.info("Created incremental diff file: %s", diff_path.name)
    return DiffResult(
        new_count=new_count,
        known_count=known_count,
        files_transformed=fetched,
        fetch_failures=fetch_failures,
        diff_path=diff_path,
        master_path=master_path,
    )


def commit_known(ctx: RunContext, diff: DiffResult) -> None:
    commit_master(
        objects=ctx.objects,
        master_path=diff.master_path,
        ledger=ctx.ledger,
        snapshots=ctx.snapshots,
        # The union master is the known set plus exactly the new records.
        record_count=diff.known_count + diff.new_count,
    )
