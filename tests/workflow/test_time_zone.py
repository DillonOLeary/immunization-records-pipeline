"""Periods and dates follow the district's calendar; the ledger stays UTC.

The case that motivated it: Cloud Run's clock is UTC while the schedulers
run on Chicago time, so a manual run on the evening of a month's last day
used to claim *next* month's roster period (and date its diff tomorrow).
"""

import json
from datetime import UTC, date, datetime

from mn_immunization.adapters.gcs.ledger import GcsRunLedger
from mn_immunization.records.ic_format import parse_ic_csv
from mn_immunization.workflow import events
from mn_immunization.workflow.steps import delivery, submit
from tests.fakes import FakeBucket, FakeClock, make_run_context

SEPT_30_10PM_CHICAGO = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)


def test_the_evening_of_a_months_last_day_is_still_that_month(tmp_path):
    ctx = make_run_context(tmp_path, clock=FakeClock(SEPT_30_10PM_CHICAGO).as_clock())

    assert submit.query_period(ctx) == "2026-09"
    assert ctx.local_now().date() == date(2026, 9, 30)


def test_delivered_files_carry_the_district_date_and_time(tmp_path):
    ctx = make_run_context(tmp_path, clock=FakeClock(SEPT_30_10PM_CHICAGO).as_clock())
    new = parse_ic_csv("8100231,9100231,MMR,01/15/2024\n")

    delivery.deliver_records(ctx, new, "new")

    assert ctx.delivery.uploads == ["2026-09-30_2200_new_01-of-01.csv"]


def test_ledger_stamps_stay_utc_in_the_existing_format():
    bucket = FakeBucket()
    ledger = GcsRunLedger(bucket, "run-x", now=lambda: SEPT_30_10PM_CHICAGO)

    ledger.append(events.run_started("run", "manual"))

    ((name, text),) = bucket.objects.items()
    assert name == "ledger/2026/10/run-x/001_RunStarted.json"
    assert json.loads(text)["at"] == "2026-10-01T03:00:00"
