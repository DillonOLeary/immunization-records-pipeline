"""Delivery: records into the import queue as capped files, at most once
per content; and noticing which delivered files staff have since
imported."""

from __future__ import annotations

import logging
from datetime import datetime

from mn_immunization.records.hashing import sha256_hex
from mn_immunization.records.ic_format import chunk, render_csv
from mn_immunization.records.model import RecordSet
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


def delivery_files(
    records: RecordSet, stem: str, max_rows: int
) -> list[tuple[str, RecordSet]]:
    """`records` as files of at most `max_rows`, named `<stem>_NN-of-MM.csv`.
    Which records share a file carries no meaning; schools are mixed."""
    pieces = chunk(records, max_rows)
    return [
        (f"{stem}_{index:02d}-of-{len(pieces):02d}.csv", piece)
        for index, piece in enumerate(pieces, start=1)
    ]


def _stem(ctx: RunContext, kind: str, taken: set[str]) -> str:
    """`YYYY-MM-DD_HHMM_<kind>` in district-local time: readable, sorted,
    unique per delivery. Seconds are added only if another delivery
    already used the minute."""
    now = ctx.local_now()
    stem = f"{now:%Y-%m-%d_%H%M}_{kind}"
    if any(name.startswith(f"{stem}_") for name in taken):
        stem = f"{now:%Y-%m-%d_%H%M%S}_{kind}"
    return stem


def deliver_records(ctx: RunContext, records: RecordSet, kind: str) -> tuple[str, int]:
    """Deliver `records` as capped files, at most once per content.
    Returns ("delivered" or "already_delivered", the number of files).
    An upload failure propagates, so the run fails loudly with the known
    set untouched.

    The claim is the date, the kind, and the content's hash: two runs with
    the same content (a crash between delivery and commit, then a rerun)
    race for one claim and deliver once; two runs the same day with
    different content both deliver. Every file is recorded as part NN of
    MM, so a crash partway through is finished by the rerun, sending only
    the missing parts under the same names.
    """
    if ctx.delivery is None:
        raise RuntimeError("no Drive folder configured")
    digest = sha256_hex(render_csv(records))
    claim_kind = "diff" if kind == "new" else kind
    date_str = ctx.local_now().strftime("%Y-%m-%d")
    won = claim_or_proceed(ctx.ledger, f"{date_str}_{claim_kind}_{digest[:16]}")
    try:
        history = ctx.history()
        sent, taken = history.delivered_parts(digest), set(history.deliveries())
    except Exception as error:
        # Errs toward delivering: a duplicate is survivable (IC imports
        # are idempotent), a delivery that never happens is not.
        logger.warning(
            "could not read recent runs (%s); assuming not delivered",
            type(error).__name__,
        )
        sent, taken = {}, set()

    max_rows = ctx.settings.delivery_file_rows
    count = len(chunk(records, max_rows))
    if sent and len(sent) >= count:
        logger.info("Skipping delivery: this content was already delivered")
        return "already_delivered", count
    if not won and not sent:
        logger.warning(
            "delivery claim for %s already taken but nothing of this content "
            "delivered; delivering anyway (a claimant that crashed before "
            "uploading must not suppress delivery)",
            date_str,
        )
    # Finish a partial delivery under its own names; otherwise a new stem.
    stem = next(iter(sent.values())).rsplit("_", 1)[0] if sent else None
    files = delivery_files(records, stem or _stem(ctx, kind, taken), max_rows)
    for part, (name, piece) in enumerate(files, start=1):
        if part in sent:
            continue
        remote_id = ctx.delivery.upload(name, render_csv(piece))
        append_event(
            ctx.ledger,
            events.delivered(
                name,
                "drive",
                str(remote_id),
                content_hash=digest,
                part=part,
                parts=len(files),
                rows=len(piece),
            ),
        )
        logger.info("Delivered %s (%d records)", name, len(piece))
    return "delivered", len(files)


def deliver_diff(ctx: RunContext, diff: DiffResult) -> str:
    """The period's new records, as `new` files. Returns "delivered" or
    "already_delivered"."""
    outcome, _ = deliver_records(ctx, diff.new_records, "new")
    return outcome
