"""Incremental diff processing, split into compute and commit on purpose.

`compute_diff` only reads durable state and writes to temp (plus an
archive copy of the diff in GCS, for forensics on blocked runs);
`commit_master` is the one function that advances durable state, and the
runner calls it only after Drive delivery succeeded. That ordering is
the fix for the old shape's flaw, where the master absorbed records
before the sanity brake fired and before delivery was known to work.

The master is the union of everything ever seen: absence is never
deletion, so a school whose download fails keeps its records and does
not get re-delivered as "new" when it recovers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from mn_immunization.domain.ic_format import (
    IcFormatError,
    parse_ic_csv,
    render_csv,
)
from mn_immunization.domain.records import RecordSet
from mn_immunization.gcp.storage import (
    download_from_storage,
    upload_file_to_storage,
)
from mn_immunization.ledger import events
from mn_immunization.ledger.gcs_ledger import sha256_hex
from mn_immunization.pipeline.support import append_event

logger = logging.getLogger(__name__)

# Master file name in GCS output folder
ALL_KNOWN_VACCINATIONS_FILE = "all_known_vaccinations.csv"


def combine_ic_files(paths: list[Path]) -> RecordSet:
    """Combine IC-format CSV files into one deduplicated RecordSet.

    Files that cannot be parsed are logged and skipped: one bad school
    file must not sink the rest.
    """
    combined = RecordSet()
    for file_path in paths:
        try:
            records = parse_ic_csv(Path(file_path).read_text(encoding="utf-8"))
        except (IcFormatError, OSError) as error:
            logger.error("Failed to read %s: %s", file_path, error)
            continue
        combined = combined.union(records)
        logger.info("Added %d records from %s", len(records), Path(file_path).name)

    logger.info(
        "Combined dataset contains %d unique vaccination records", len(combined)
    )
    return combined


def load_known_records(bucket_name: str, temp_dir: Path) -> RecordSet:
    """Load the known-vaccinations master file from GCS.

    Any failure yields an empty set: the pipeline then treats all current
    records as new, which is safe for a first run and — combined with the
    sanity brake — loud instead of harmful otherwise.
    """
    master_file_path = temp_dir / ALL_KNOWN_VACCINATIONS_FILE
    blob_name = f"output/{ALL_KNOWN_VACCINATIONS_FILE}"
    try:
        download_from_storage(bucket_name, blob_name, str(master_file_path))
        known = parse_ic_csv(master_file_path.read_text(encoding="utf-8"))
        logger.info("Loaded %d known vaccination records", len(known))
        return known
    except Exception as error:
        logger.info("Master file not found or couldn't be loaded: %s", error)
        return RecordSet()


def compute_diff(
    output_files: list[Path],
    output_folder: Path,
    bucket_name: str,
    temp_dir: Path,
    ledger,
) -> tuple[Path, Path, int, int]:
    """Diff current records against the known set; write both files to temp.

    Returns (diff_path, master_path, new_count, known_count). Nothing
    durable moves here: the master upload and snapshot wait for
    `commit_master`, after delivery. The diff archive copy in GCS is
    best-effort — useful for inspecting a brake-blocked diff without
    putting record content in logs, but never load-bearing.
    """
    current_records = combine_ic_files(output_files)
    known_records = load_known_records(bucket_name, temp_dir)

    new_records = current_records.diff(known_records)
    master_records = known_records.union(current_records)
    logger.info(
        "Found %d new vaccination records out of %d total",
        len(new_records),
        len(current_records),
    )

    date_str = datetime.now().strftime("%Y-%m-%d")
    diff_filename = f"{date_str}_new_vaccinations.csv"
    diff_path = output_folder / diff_filename
    diff_text = render_csv(new_records)
    diff_path.write_text(diff_text, encoding="utf-8")

    master_path = output_folder / ALL_KNOWN_VACCINATIONS_FILE
    master_path.write_text(render_csv(master_records), encoding="utf-8")

    append_event(
        ledger,
        events.diff_computed(
            new_count=len(new_records),
            total_count=len(current_records),
            known_hash=sha256_hex(render_csv(known_records)),
            diff_hash=sha256_hex(diff_text),
            snapshot_path="",
        ),
    )

    try:
        upload_file_to_storage(
            bucket_name, f"output/changes/{diff_filename}", str(diff_path)
        )
    except Exception as error:
        logger.error("Archive upload of diff to GCS failed: %s", error)

    return diff_path, master_path, len(new_records), len(known_records)


def commit_master(
    bucket_name: str,
    master_path: Path,
    ledger,
    snapshots,
    record_count: int,
) -> None:
    """Advance durable state: upload the union master and snapshot it.

    Failures propagate on purpose. A delivered-but-uncommitted run must
    fail loudly so a rerun redoes the commit — which is safe, because
    the master is a union and committing it twice changes nothing.
    """
    master_text = master_path.read_text(encoding="utf-8")
    upload_file_to_storage(
        bucket_name, f"output/{ALL_KNOWN_VACCINATIONS_FILE}", str(master_path)
    )
    logger.info("Updated master file with %d total records", record_count)

    snapshot_path = ""
    try:
        _, snapshot_path = snapshots.put(master_text)
    except Exception as error:
        logger.warning("snapshot store failed: %s", error)

    append_event(
        ledger,
        events.master_committed(
            master_hash=sha256_hex(master_text),
            record_count=record_count,
            snapshot_path=snapshot_path,
        ),
    )
