"""transform_downloads: raw AISR files in, IC files out, failures counted.

The count matters because the policy reads it: a run where every school's
file fails to parse (say, MIIC changes its format) must end
AllDownloadsFailed, not as an empty "success" that delivers nothing.
"""

from mn_immunization.pipeline.execute import transform_downloads
from mn_immunization.pipeline.policy import (
    CycleState,
    DiffResult,
    Finish,
    Submission,
    decide,
)

HEADER = "id_1|id_2|vaccine_group_name|vaccination_date"


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_good_files_are_written_and_bad_ones_counted(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    good = write(tmp_path / "a.csv", f"{HEADER}\n123|456|MMR|2024-11-17\n")
    bad = write(tmp_path / "b.csv", "a|format|MIIC|changed\n1|2|3|4\n")

    written, failures = transform_downloads([good, bad], out)

    assert [p.name for p in written] == ["transformed_a.csv"]
    assert written[0].read_text(encoding="utf-8") == "123,456,MMR,11/17/2024\n"
    assert failures == 1


def test_failure_logs_carry_the_class_never_the_value(tmp_path, caplog):
    out = tmp_path / "out"
    out.mkdir()
    bad = write(tmp_path / "b.csv", f"{HEADER}\n123|456|MMR|Zelda Canaryfield\n")

    transform_downloads([bad], out)

    assert "AisrParseError" in caplog.text
    assert "Zelda" not in caplog.text


def test_every_file_unparseable_is_a_failed_run_not_a_success(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    inputs = [write(tmp_path / f"{n}.csv", "not|the|format\n") for n in "abc"]

    written, failures = transform_downloads(inputs, out)
    diff = DiffResult(
        new_count=0,
        known_count=170_361,
        files_transformed=len(written),
        fetch_failures=0 + failures,  # downloads all succeeded
        diff_path=tmp_path / "diff.csv",
        master_path=tmp_path / "master.csv",
    )
    submission = Submission(submitted=frozenset({"1", "2", "3"}))
    state = CycleState().with_submission(submission).with_staged(3).with_diff(diff)

    step = decide(state, 0.2)

    assert isinstance(step, Finish)
    assert (step.status, step.error) == ("failed", "AllDownloadsFailed")
