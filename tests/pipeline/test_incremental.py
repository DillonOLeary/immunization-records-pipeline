"""Tests for the diff-processing helpers: combine and the known set."""

from pathlib import Path

import pytest
from google.api_core.exceptions import NotFound, ServiceUnavailable

import mn_immunization.pipeline.incremental as incremental
from mn_immunization.domain.ic_format import IcFormatError
from mn_immunization.domain.records import RecordSet, VaccinationRecord
from mn_immunization.pipeline.incremental import (
    MasterMissingError,
    combine_ic_files,
    load_known_records,
)


def write_ic_file(path: Path, rows: list[str]) -> Path:
    path.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")
    return path


def test_combine_empty_list_returns_empty_set():
    assert combine_ic_files([]) == RecordSet()


def test_combine_valid_files(tmp_path):
    file1 = write_ic_file(
        tmp_path / "school1.csv",
        ["12345,678901,MMR,01/15/2024", "12346,678902,Polio,02/01/2024"],
    )
    file2 = write_ic_file(tmp_path / "school2.csv", ["12347,678903,DPT,01/20/2024"])

    result = combine_ic_files([file1, file2])

    assert len(result) == 3
    assert result.records[0].id_1 == "12345"
    assert result.records[2].vaccine_group == "DPT"


def test_combine_removes_duplicates_across_schools(tmp_path):
    file1 = write_ic_file(
        tmp_path / "school1.csv",
        ["12345,678901,MMR,01/15/2024", "12346,678902,Polio,02/01/2024"],
    )
    file2 = write_ic_file(
        tmp_path / "school2.csv",
        ["12345,678901,MMR,01/15/2024", "12347,678903,DPT,01/20/2024"],
    )

    result = combine_ic_files([file1, file2])

    assert len(result) == 3
    duplicate = VaccinationRecord.create("12345", "678901", "MMR", "01/15/2024")
    assert sum(1 for r in result if r == duplicate) == 1


def test_combine_skips_unparseable_files(tmp_path):
    bad = write_ic_file(tmp_path / "invalid.csv", ["12345,678901"])
    good = write_ic_file(tmp_path / "valid.csv", ["12347,678903,DPT,01/20/2024"])

    result = combine_ic_files([bad, good])

    assert len(result) == 1
    assert result.records[0].id_1 == "12347"


# --- load_known_records fails closed ---
#
# An empty known set disables the sanity brake and makes every current
# record "new", so only a master that never existed may load as empty.
# GCS is stubbed at the module's two storage helpers so no test can reach
# real storage with the developer's ambient credentials.


def stub_storage(monkeypatch, master: str | Exception, snapshots_exist: bool):
    """`master` is the master file's text, or the exception its download
    raises."""

    def download(_bucket, _blob, destination):
        if isinstance(master, Exception):
            raise master
        Path(destination).write_text(master, encoding="utf-8")

    monkeypatch.setattr(incremental, "download_from_storage", download)
    monkeypatch.setattr(
        incremental, "prefix_has_objects", lambda _bucket, _prefix: snapshots_exist
    )


def test_master_absent_on_a_first_run_is_an_empty_known_set(tmp_path, monkeypatch):
    stub_storage(monkeypatch, NotFound("no master"), snapshots_exist=False)
    assert load_known_records("test-bucket", tmp_path) == RecordSet()


def test_master_absent_after_a_commit_is_master_missing(tmp_path, monkeypatch):
    # Snapshots prove a master was committed; its absence is damage, not a
    # first run. Treating it as empty would deliver the whole known set.
    stub_storage(monkeypatch, NotFound("no master"), snapshots_exist=True)
    with pytest.raises(MasterMissingError):
        load_known_records("test-bucket", tmp_path)


def test_master_empty_after_a_commit_is_master_missing(tmp_path, monkeypatch):
    stub_storage(monkeypatch, "", snapshots_exist=True)
    with pytest.raises(MasterMissingError):
        load_known_records("test-bucket", tmp_path)


def test_transient_read_error_propagates(tmp_path, monkeypatch):
    stub_storage(monkeypatch, ServiceUnavailable("try later"), snapshots_exist=True)
    with pytest.raises(ServiceUnavailable):
        load_known_records("test-bucket", tmp_path)


def test_one_malformed_row_fails_the_load(tmp_path, monkeypatch):
    # One bad line must not turn the whole known set into zero records.
    master = "12345,678901,MMR,01/15/2024\n12346,678902\n"
    stub_storage(monkeypatch, master, snapshots_exist=True)
    with pytest.raises(IcFormatError):
        load_known_records("test-bucket", tmp_path)


def test_healthy_master_loads(tmp_path, monkeypatch):
    master = "12345,678901,MMR,01/15/2024\n12346,678902,Polio,02/01/2024\n"
    stub_storage(monkeypatch, master, snapshots_exist=True)
    known = load_known_records("test-bucket", tmp_path)
    assert len(known) == 2
