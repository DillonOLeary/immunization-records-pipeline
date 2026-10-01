"""Incremental diff processing, split into compute and commit on purpose.

`compute_diff` only reads durable state and writes to temp (plus an
archive copy of the diff, for forensics on blocked runs); `commit_master`
is the one function that advances durable state, and the runner calls it
only after Drive delivery succeeded. That ordering is the fix for the old
shape's flaw, where the master absorbed records before the sanity brake
fired and before delivery was known to work.

The master is the union of everything ever seen: absence is never
deletion, so a school whose download fails keeps its records and does
not get re-delivered as "new" when it recovers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from mn_immunization.domain.hashing import sha256_hex
from mn_immunization.domain.ic_format import parse_ic_csv, render_csv
from mn_immunization.domain.records import RecordSet
from mn_immunization.gcp.port import ObjectNotFoundError, ObjectStore
from mn_immunization.ledger import events
from mn_immunization.ledger.port import RunLedger, SnapshotStore
from mn_immunization.pipeline.support import append_event

logger = logging.getLogger(__name__)

ALL_KNOWN_VACCINATIONS_FILE = "all_known_vaccinations.csv"
MASTER_PATH = f"output/{ALL_KNOWN_VACCINATIONS_FILE}"


class MasterMissingError(Exception):
    """The master is absent or empty, yet a master was committed before
    (snapshots exist). Treating that as a first run would deliver every
    record as new and overwrite the union master with only the current
    set, so it fails the run instead."""


def load_known_records(objects: ObjectStore, snapshots: SnapshotStore) -> RecordSet:
    """Load the known-vaccinations master. Fails closed.

    Only a master that has never existed is an empty known set: that is a
    genuine first run, and the sanity brake rightly exempts it. Anything
    else must fail the run, because an empty known set disables the brake
    and makes every current record "new":

    - absent or empty while snapshots exist -> MasterMissingError (it
      existed once; something deleted or truncated it);
    - a transient read error -> propagates (RunFailed, rerun later);
    - a malformed row -> IcFormatError propagates (one bad line must not
      turn 170k known records into zero).
    """
    try:
        text = objects.read_text(MASTER_PATH)
    except ObjectNotFoundError:
        if snapshots.any_stored():
            raise MasterMissingError("master absent but snapshots exist") from None
        logger.info("No master file yet: first run, known set is empty")
        return RecordSet()

    known = parse_ic_csv(text)
    if not known and snapshots.any_stored():
        raise MasterMissingError("master empty but snapshots exist")
    logger.info("Loaded %d known vaccination records", len(known))
    return known


def compute_diff(
    current: RecordSet,
    output_folder: Path,
    objects: ObjectStore,
    snapshots: SnapshotStore,
    ledger: RunLedger,
) -> tuple[Path, Path, int, int]:
    """Diff current records against the known set; write both files to temp.

    Returns (diff_path, master_path, new_count, known_count). Nothing
    durable moves here: the master upload and snapshot wait for
    `commit_master`, after delivery. The diff archive copy is best-effort
    — useful for inspecting a brake-blocked diff without putting record
    content in logs, but never load-bearing.
    """
    known_records = load_known_records(objects, snapshots)

    new_records = current.diff(known_records)
    master_records = known_records.union(current)
    logger.info(
        "Found %d new vaccination records out of %d total",
        len(new_records),
        len(current),
    )

    diff_filename = f"{datetime.now():%Y-%m-%d}_new_vaccinations.csv"
    diff_path = output_folder / diff_filename
    diff_text = render_csv(new_records)
    diff_path.write_text(diff_text, encoding="utf-8")

    master_path = output_folder / ALL_KNOWN_VACCINATIONS_FILE
    master_path.write_text(render_csv(master_records), encoding="utf-8")

    append_event(
        ledger,
        events.diff_computed(
            new_count=len(new_records),
            total_count=len(current),
            known_hash=sha256_hex(render_csv(known_records)),
            diff_hash=sha256_hex(diff_text),
        ),
    )

    try:
        objects.write_text(f"output/changes/{diff_filename}", diff_text, "text/csv")
    except Exception as error:
        logger.error("Archive upload of diff failed: %s", type(error).__name__)

    return diff_path, master_path, len(new_records), len(known_records)


def commit_master(
    objects: ObjectStore,
    master_path: Path,
    ledger: RunLedger,
    snapshots: SnapshotStore,
    record_count: int,
) -> None:
    """Advance durable state: write the union master and snapshot it.

    Failures propagate on purpose. A delivered-but-uncommitted run must
    fail loudly so a rerun redoes the commit — which is safe, because
    the master is a union and committing it twice changes nothing.
    """
    master_text = master_path.read_text(encoding="utf-8")
    objects.write_text(MASTER_PATH, master_text, "text/csv")
    logger.info("Updated master file with %d total records", record_count)

    snapshot_path = ""
    try:
        _, snapshot_path = snapshots.put(master_text)
    except Exception as error:
        logger.warning("snapshot store failed: %s", type(error).__name__)

    append_event(
        ledger,
        events.master_committed(
            master_hash=sha256_hex(master_text),
            record_count=record_count,
            snapshot_path=snapshot_path,
        ),
    )
