"""Tests for the diff-processing helpers: combine and the known set."""

from pathlib import Path

from mn_immunization.domain.records import RecordSet, VaccinationRecord
from mn_immunization.pipeline.incremental import combine_ic_files, load_known_records


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


def test_load_known_records_without_cloud_storage_returns_empty(tmp_path):
    assert load_known_records("test-bucket", tmp_path) == RecordSet()
