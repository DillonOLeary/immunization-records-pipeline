"""Delivery: the diff into the import queue, at most once per content;
and noticing which delivered files staff have since imported."""

from __future__ import annotations

import logging
from datetime import datetime

from mn_immunization.records.hashing import sha256_hex
from mn_immunization.workflow import events
from mn_immunization.workflow.context import RunContext
from mn_immunization.workflow.policy import DiffResult
from mn_immunization.workflow.support import append_event, claim_or_proceed

logger = logging.getLogger(__name__)


def _days_since_prefix_date(filename: str, now: datetime) -> int | None:
    """Delivered files are named `YYYY-MM-DD_...`; return the age in days,
    or None if the prefix is not a date."""
    try:
        delivered = datetime.strptime(filename[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return (now - delivered).days


def record_import_confirmations(ctx: RunContext) -> None:
    """Notice which delivered files staff have imported and record it.

    The Drive protocol is delete-as-ack: a delivered file that is gone
    from the folder was imported into Infinite Campus. This lists the
    folder, and for each Delivered file not already ImportConfirmed:
    absent -> append ImportConfirmed; still present past
    IMPORT_REMINDER_DAYS -> a warning (true absence alerting waits for a
    weekly cadence, per alerts.tf).

    Entirely best-effort: any failure is logged and swallowed, because a
    confirmation check must never sink a delivery run.
    """
    if ctx.delivery is None:
        return

    try:
        # Delivered files carry the district-local date they were made on.
        now = ctx.local_now().replace(tzinfo=None)
        history = ctx.history()
        outstanding = set(history.deliveries()) - history.confirmed_imports()
        if not outstanding:
            return
        present = ctx.delivery.list_filenames()
    except Exception as error:
        logger.warning("import-confirmation check skipped (%s)", type(error).__name__)
        return

    reminder_days = ctx.settings.import_reminder_days
    for filename in sorted(outstanding):
        if filename not in present:
            append_event(
                ctx.ledger, events.import_confirmed(filename, "deleted from Drive")
            )
            logger.info("Import confirmed (deleted from Drive): %s", filename)
        else:
            age = _days_since_prefix_date(filename, now)
            if age is not None and age >= reminder_days:
                logger.warning(
                    "Delivered file still awaiting import after %d days: %s",
                    age,
                    filename,
                )


def _drive_deliveries(ctx: RunContext) -> dict[str, str]:
    """Recent Drive deliveries: file name -> content hash ("" for ones
    recorded before hashes were). Empty if the ledger cannot be read,
    which errs toward delivering: zero deliveries is the unacceptable
    failure, a duplicate the survivable one."""
    try:
        return ctx.history().deliveries()
    except Exception as error:
        logger.warning(
            "could not read recent runs (%s); assuming not delivered",
            type(error).__name__,
        )
        return {}


def _unused_name(name: str, deliveries: dict[str, str]) -> str:
    """`name`, or `<stem>_2.csv`, `_3`, ... when a different diff already
    went out under it (a second run the same day with new records): every
    delivery gets its own file, and none masks another."""
    stem, suffix = name.rsplit(".", 1)
    candidate, n = name, 2
    while candidate in deliveries:
        candidate, n = f"{stem}_{n}.{suffix}", n + 1
    return candidate


def deliver_diff(ctx: RunContext, diff: DiffResult) -> str:
    """Drive delivery, at most once per diff *content*. Returns "delivered"
    or "already_delivered"; an upload failure propagates so the run fails
    loudly with the master untouched.

    The claim is the date plus the diff's hash: two runs with the same
    diff (a crash between delivery and commit, then a rerun) race for one
    claim and deliver once; two runs the same day with different diffs
    (new records arrived in between) both deliver. Keying on the date
    alone made the second one look "already delivered", and its records
    would have been committed to the master without ever reaching staff.
    """
    if ctx.delivery is None:
        raise RuntimeError("no Drive folder configured")
    text = diff.diff_path.read_text(encoding="utf-8")
    digest = sha256_hex(text)
    # The filename starts with the %Y-%m-%d the diff was computed on; the
    # claim shares that date so a run crossing midnight stays consistent.
    date_str = diff.diff_path.name[:10]
    won = claim_or_proceed(ctx.ledger, f"{date_str}_diff_{digest[:16]}")
    deliveries = _drive_deliveries(ctx)
    if not won:
        if digest in deliveries.values():
            logger.info("Skipping delivery: this diff was already delivered")
            return "already_delivered"
        logger.warning(
            "diff claim for %s already taken but no delivery of this content "
            "found; delivering anyway (a claimant that crashed before "
            "uploading must not suppress delivery)",
            date_str,
        )
    name = _unused_name(diff.diff_path.name, deliveries)
    drive_file_id = ctx.delivery.upload(name, text)
    append_event(
        ctx.ledger,
        events.delivered(name, "drive", str(drive_file_id), content_hash=digest),
    )
    logger.info("Delivered the diff as %s", name)
    return "delivered"
