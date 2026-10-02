"""The known set: every record already delivered, the one PHI cache.

`load_known_records` reads it, `diff_against_known` splits fetched
records into new and known (reads only), and `commit_known` writes it
forward. The runner commits only after delivery succeeded, so a failed
delivery leaves the set untouched and its records in the next diff.

Between refreshes the set only grows: absence from a fetch is never
deletion, so a school whose download fails is not re-delivered as "new"
when it recovers. `refresh` replaces it with exactly what MIIC lists.
"""

from __future__ import annotations

import json
import logging

from mn_immunization.records.hashing import sha256_hex
from mn_immunization.records.ic_format import parse_ic_csv, render_csv
from mn_immunization.records.model import RecordSet
from mn_immunization.workflow import events
from mn_immunization.workflow.layout import KNOWN_MARKER, KNOWN_RECORDS
from mn_immunization.workflow.ports import ObjectNotFoundError, ObjectStore, RunLedger
from mn_immunization.workflow.support import append_event

logger = logging.getLogger(__name__)


class KnownRecordsMissingError(Exception):
    """The known set is absent or empty, yet one was committed before (its
    marker exists). Treating that as a first run would deliver every
    record as new, so it fails instead; `refresh` rebuilds the set."""


def load_known_records(objects: ObjectStore) -> RecordSet:
    """Load the known set. Fails closed.

    Only a set that was never committed (no records, no marker) is empty:
    a first run, or a cache cleared on purpose, and the brake rightly
    exempts it. Anything else fails the run, because an empty known set
    disables the brake and makes every current record "new":

    - absent or empty while the marker exists -> KnownRecordsMissingError;
    - a transient read error -> propagates (RunFailed, rerun later);
    - a malformed row -> IcFormatError propagates (one bad line must not
      turn 180k known records into zero).
    """
    try:
        text = objects.read_text(KNOWN_RECORDS)
    except ObjectNotFoundError:
        if _committed_before(objects):
            raise KnownRecordsMissingError("known set absent, marker present") from None
        logger.info("No known set yet: first run, known set is empty")
        return RecordSet()

    known = parse_ic_csv(text)
    if not known and _committed_before(objects):
        raise KnownRecordsMissingError("known set empty, marker present")
    logger.info("Loaded %d known vaccination records", len(known))
    return known


def _committed_before(objects: ObjectStore) -> bool:
    try:
        objects.read_text(KNOWN_MARKER)
    except ObjectNotFoundError:
        return False
    return True


def diff_against_known(
    current: RecordSet, objects: ObjectStore, ledger: RunLedger
) -> tuple[RecordSet, RecordSet, int]:
    """Split fetched records against the known set. Returns (new records,
    the known set grown by `current`, the known count). Reads only."""
    known = load_known_records(objects)
    new = current.diff(known)
    logger.info(
        "Found %d new vaccination records out of %d total", len(new), len(current)
    )
    append_event(
        ledger,
        events.diff_computed(
            new_count=len(new),
            total_count=len(current),
            known_hash=sha256_hex(render_csv(known)),
            diff_hash=sha256_hex(render_csv(new)),
        ),
    )
    return new, known.union(current), len(known)


def commit_known(objects: ObjectStore, records: RecordSet, ledger: RunLedger) -> None:
    """Write the known set, then its marker. Failures propagate on purpose:
    a delivered-but-uncommitted run must fail loudly so a rerun redoes the
    commit, which is safe because the set is a union."""
    text = render_csv(records)
    digest = sha256_hex(text)
    objects.write_text(KNOWN_RECORDS, text, "text/csv")
    objects.write_text(
        KNOWN_MARKER,
        json.dumps({"records": len(records), "sha256": digest}),
        "application/json",
    )
    logger.info("Known set committed: %d records", len(records))
    append_event(
        ledger, events.master_committed(master_hash=digest, record_count=len(records))
    )
