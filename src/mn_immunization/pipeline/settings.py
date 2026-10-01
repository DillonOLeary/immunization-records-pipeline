"""Settings: every environment variable the pipeline reads, parsed once.

`Settings.from_env` is called by the job entrypoint and nowhere else; the
pipeline receives the result. A missing or malformed value fails at
startup with the variable's name, before any run begins, instead of
deep inside a cycle (or, worse, after a roster went out).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SettingsError(ValueError):
    """An environment variable is missing or malformed. Carries the
    variable's name and what is wrong with it, never its value."""

    def __init__(self, variable: str, problem: str):
        super().__init__(f"{variable} {problem}")
        self.variable = variable
        self.problem = problem


def _int(env: Mapping[str, str], name: str, default: int, minimum: int = 0) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(name, "must be an integer") from None
    if value < minimum:
        raise SettingsError(name, f"must be at least {minimum}")
    return value


def _brake(env: Mapping[str, str]) -> float | None:
    raw = env.get("DIFF_SANITY_FRACTION", "0.2")
    if raw == "off":
        return None
    try:
        value = float(raw)
    except ValueError:
        raise SettingsError(
            "DIFF_SANITY_FRACTION", "must be a number or 'off'"
        ) from None
    if value <= 0:
        raise SettingsError("DIFF_SANITY_FRACTION", "must be positive (or 'off')")
    return value


def _zone(env: Mapping[str, str]) -> ZoneInfo:
    name = env.get("DISTRICT_TIME_ZONE")
    if not name:
        # No code default: the zone decides which month's rosters go out.
        raise SettingsError("DISTRICT_TIME_ZONE", "is not set")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise SettingsError("DISTRICT_TIME_ZONE", "is not a known time zone") from None


@dataclass(frozen=True)
class Settings:
    data_bucket: str  # DATA_BUCKET: the district's one bucket
    time_zone: ZoneInfo  # DISTRICT_TIME_ZONE: periods and dates are local
    gcp_project: str | None = None  # GCP_PROJECT; None: from ADC
    drive_folder_id: str | None = None  # GOOGLE_DRIVE_FOLDER_ID; None: no delivery
    poll_interval_seconds: int = 14400  # POLL_INTERVAL_SECONDS
    poll_deadline_seconds: int = 72000  # POLL_DEADLINE_SECONDS
    brake_fraction: float | None = 0.2  # DIFF_SANITY_FRACTION; "off" -> None
    query_period_format: str = "%Y-%m"  # QUERY_PERIOD_FORMAT
    import_reminder_days: int = 7  # IMPORT_REMINDER_DAYS
    rebaseline_chunk_records: int = 10000  # REBASELINE_CHUNK_RECORDS

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        bucket = env.get("DATA_BUCKET")
        if not bucket:
            raise SettingsError("DATA_BUCKET", "is not set")
        return cls(
            data_bucket=bucket,
            time_zone=_zone(env),
            gcp_project=env.get("GCP_PROJECT") or None,
            drive_folder_id=env.get("GOOGLE_DRIVE_FOLDER_ID") or None,
            poll_interval_seconds=_int(env, "POLL_INTERVAL_SECONDS", 14400),
            poll_deadline_seconds=_int(env, "POLL_DEADLINE_SECONDS", 72000),
            brake_fraction=_brake(env),
            query_period_format=env.get("QUERY_PERIOD_FORMAT") or "%Y-%m",
            import_reminder_days=_int(env, "IMPORT_REMINDER_DAYS", 7),
            rebaseline_chunk_records=_int(
                env, "REBASELINE_CHUNK_RECORDS", 10000, minimum=1
            ),
        )
