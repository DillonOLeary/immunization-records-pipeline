"""Settings.from_env: every environment variable, parsed once, loudly."""

import pytest

from mn_immunization.pipeline.settings import Settings, SettingsError


def test_defaults_need_only_the_bucket():
    settings = Settings.from_env({"DATA_BUCKET": "b"})
    assert settings == Settings(data_bucket="b")
    assert settings.brake_fraction == 0.2
    assert settings.drive_folder_id is None


def test_every_variable_is_read():
    env = {
        "DATA_BUCKET": "b",
        "GCP_PROJECT": "p",
        "GOOGLE_DRIVE_FOLDER_ID": "f",
        "POLL_INTERVAL_SECONDS": "60",
        "POLL_DEADLINE_SECONDS": "600",
        "DIFF_SANITY_FRACTION": "0.5",
        "QUERY_PERIOD_FORMAT": "%G-W%V",
        "IMPORT_REMINDER_DAYS": "3",
        "REBASELINE_CHUNK_RECORDS": "500",
    }
    assert Settings.from_env(env) == Settings(
        data_bucket="b",
        gcp_project="p",
        drive_folder_id="f",
        poll_interval_seconds=60,
        poll_deadline_seconds=600,
        brake_fraction=0.5,
        query_period_format="%G-W%V",
        import_reminder_days=3,
        rebaseline_chunk_records=500,
    )


def test_the_brake_can_be_turned_off():
    env = {"DATA_BUCKET": "b", "DIFF_SANITY_FRACTION": "off"}
    assert Settings.from_env(env).brake_fraction is None


def test_empty_optional_values_mean_unset():
    env = {"DATA_BUCKET": "b", "GOOGLE_DRIVE_FOLDER_ID": "", "GCP_PROJECT": ""}
    settings = Settings.from_env(env)
    assert (settings.drive_folder_id, settings.gcp_project) == (None, None)


@pytest.mark.parametrize(
    ("env", "variable"),
    [
        ({}, "DATA_BUCKET"),
        (
            {"DATA_BUCKET": "b", "POLL_DEADLINE_SECONDS": "soon"},
            "POLL_DEADLINE_SECONDS",
        ),
        (
            {"DATA_BUCKET": "b", "REBASELINE_CHUNK_RECORDS": "0"},
            "REBASELINE_CHUNK_RECORDS",
        ),
        ({"DATA_BUCKET": "b", "DIFF_SANITY_FRACTION": "lots"}, "DIFF_SANITY_FRACTION"),
        ({"DATA_BUCKET": "b", "DIFF_SANITY_FRACTION": "-1"}, "DIFF_SANITY_FRACTION"),
    ],
)
def test_bad_values_fail_naming_the_variable(env, variable):
    with pytest.raises(SettingsError) as caught:
        Settings.from_env(env)
    assert caught.value.variable == variable
