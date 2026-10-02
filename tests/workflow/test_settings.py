"""Settings.from_env: every environment variable, parsed once, loudly."""

from zoneinfo import ZoneInfo

import pytest

from mn_immunization.workflow.settings import Settings, SettingsError

CHICAGO = ZoneInfo("America/Chicago")
BASE = {"DATA_BUCKET": "b", "DISTRICT_TIME_ZONE": "America/Chicago"}


def test_defaults_need_only_the_bucket_and_the_zone():
    settings = Settings.from_env(BASE)
    assert settings == Settings(data_bucket="b", time_zone=CHICAGO)
    assert settings.brake_fraction == 0.2
    assert settings.drive_folder_id is None


def test_every_variable_is_read():
    env = {
        **BASE,
        "GCP_PROJECT": "p",
        "GOOGLE_DRIVE_FOLDER_ID": "f",
        "POLL_DEADLINE_SECONDS": "600",
        "DIFF_SANITY_FRACTION": "0.5",
        "QUERY_PERIOD_FORMAT": "%G-W%V",
        "IMPORT_REMINDER_DAYS": "3",
        "DELIVERY_FILE_ROWS": "500",
    }
    assert Settings.from_env(env) == Settings(
        data_bucket="b",
        time_zone=CHICAGO,
        gcp_project="p",
        drive_folder_id="f",
        poll_deadline_seconds=600,
        brake_fraction=0.5,
        query_period_format="%G-W%V",
        import_reminder_days=3,
        delivery_file_rows=500,
    )


def test_the_brake_can_be_turned_off():
    env = {**BASE, "DIFF_SANITY_FRACTION": "off"}
    assert Settings.from_env(env).brake_fraction is None


def test_empty_optional_values_mean_unset():
    env = {**BASE, "GOOGLE_DRIVE_FOLDER_ID": "", "GCP_PROJECT": ""}
    settings = Settings.from_env(env)
    assert (settings.drive_folder_id, settings.gcp_project) == (None, None)


@pytest.mark.parametrize(
    ("env", "variable"),
    [
        ({"DISTRICT_TIME_ZONE": "America/Chicago"}, "DATA_BUCKET"),
        ({"DATA_BUCKET": "b"}, "DISTRICT_TIME_ZONE"),
        ({**BASE, "DISTRICT_TIME_ZONE": "Mars/Olympus_Mons"}, "DISTRICT_TIME_ZONE"),
        (
            {**BASE, "POLL_DEADLINE_SECONDS": "soon"},
            "POLL_DEADLINE_SECONDS",
        ),
        (
            {**BASE, "DELIVERY_FILE_ROWS": "0"},
            "DELIVERY_FILE_ROWS",
        ),
        ({**BASE, "DIFF_SANITY_FRACTION": "lots"}, "DIFF_SANITY_FRACTION"),
        ({**BASE, "DIFF_SANITY_FRACTION": "-1"}, "DIFF_SANITY_FRACTION"),
    ],
)
def test_bad_values_fail_naming_the_variable(env, variable):
    with pytest.raises(SettingsError) as caught:
        Settings.from_env(env)
    assert caught.value.variable == variable
