"""Per-school roster submission: never twice, and fail closed.

Every roster upload makes MIIC email every nurse in the district, so the
property under test is that a roster which may already have gone out is
never sent again, and every school that did not go out is named. These
run the real `submit_queries` against the in-process fake AISR (which
records every upload it receives) and the real GCS ledger over one
shared fake bucket, so reruns see each other's claims and events exactly
as production runs do.
"""

import json
from datetime import datetime

import pytest

from mn_immunization.adapters.gcs.ledger import GcsRunLedger
from mn_immunization.adapters.gcs.storage import GcsObjectStore
from mn_immunization.adapters.miic.actions import DistrictInfo
from mn_immunization.adapters.miic.authenticate import AuthenticationError
from mn_immunization.adapters.miic.client import SchoolUpload, aisr_session
from mn_immunization.records.hashing import sha256_hex
from mn_immunization.workflow.ports import School
from mn_immunization.workflow.steps import submit as submit_step
from tests.fakes import FakeBucket, district_period, make_run_context

SCHOOL_IDS = ["2542", "2543", "2544"]


@pytest.fixture
def bucket():
    return FakeBucket()


@pytest.fixture
def period():
    return district_period()


def make_ctx(
    bucket,
    tmp_path,
    mock_aisr,
    run_id,
    ledger_cls=GcsRunLedger,
    password="test_password",
):
    schools = []
    for school_id in SCHOOL_IDS:
        if roster_path(school_id) not in bucket.objects:
            bucket.write(roster_path(school_id), "roster rows\n")
        schools.append(
            School(
                id=school_id,
                name=f"School {school_id}",
                roster_path=roster_path(school_id),
            )
        )
    uploads = dict.fromkeys(SCHOOL_IDS, SchoolUpload("N", "nurse@example.test"))
    return make_run_context(
        tmp_path,
        ledger=ledger_cls(bucket, run_id, now=datetime.now),
        objects=GcsObjectStore(bucket),
        open_registry=lambda: aisr_session(
            mock_aisr.auth_url,
            mock_aisr.base_url,
            "test_user",
            password,
            DistrictInfo(iddis="0197", s3_upload_host="mock-s3-host"),
            uploads,
        ),
        schools=schools,
    )


def roster_path(school_id: str) -> str:
    return f"data/queries/{school_id}.csv"


def submit(ctx):
    return submit_step.submit_queries(ctx)


def claims(bucket) -> dict[str, dict]:
    prefix = "ledger/claims/"
    return {
        name[len(prefix) :]: json.loads(text)
        for name, text in bucket.objects.items()
        if name.startswith(prefix)
    }


def query_submitted_events(bucket) -> list[dict]:
    return [
        json.loads(text)
        for name, text in bucket.objects.items()
        if name.startswith("ledger/2") and name.endswith("_QuerySubmitted.json")
    ]


def assert_every_upload_was_claimed_by(bucket, uploads, run_id, period):
    """The invariant: no roster reaches MIIC without a claim this run won."""
    held = claims(bucket)
    for school_id in uploads:
        assert held[f"{period}_query_{school_id}"]["run_id"] == run_id


def test_a_fresh_period_submits_every_school_once(bucket, tmp_path, mock_aisr, period):
    ctx = make_ctx(bucket, tmp_path, mock_aisr, "run-1")

    result = submit(ctx)

    assert result.submitted == frozenset(SCHOOL_IDS)
    assert not result.incomplete
    assert mock_aisr.received_uploads == SCHOOL_IDS
    assert_every_upload_was_claimed_by(
        bucket, mock_aisr.received_uploads, "run-1", period
    )
    recorded = query_submitted_events(bucket)
    assert sorted(e["data"]["school_id"] for e in recorded) == SCHOOL_IDS
    assert {e["data"]["period"] for e in recorded} == {period}


def test_a_rerun_in_the_same_period_sends_nothing(bucket, tmp_path, mock_aisr):
    submit(make_ctx(bucket, tmp_path, mock_aisr, "run-1"))
    mock_aisr.received_uploads.clear()

    result = submit(make_ctx(bucket, tmp_path, mock_aisr, "run-2"))

    assert result.submitted == frozenset(SCHOOL_IDS)
    assert not result.incomplete
    assert mock_aisr.received_uploads == []


def test_a_claim_without_an_event_is_stuck_and_never_resent(
    bucket, tmp_path, mock_aisr, period
):
    # An earlier run claimed 2543 and crashed before recording the event:
    # it may or may not have uploaded. Skip it and say so.
    bucket.write(
        f"ledger/claims/{period}_query_2543",
        json.dumps({"run_id": "crashed-run", "at": "2026-10-28T07:10:00"}),
    )
    ctx = make_ctx(bucket, tmp_path, mock_aisr, "run-1")

    result = submit(ctx)

    assert result.stuck == frozenset({"2543"})
    assert result.submitted == frozenset({"2542", "2544"})
    assert mock_aisr.received_uploads == ["2542", "2544"]
    assert_every_upload_was_claimed_by(
        bucket, mock_aisr.received_uploads, "run-1", period
    )


def test_a_signing_failure_releases_its_claim_and_a_rerun_sends_it_once(
    bucket, tmp_path, mock_aisr, period
):
    # Signing failed, so the upload never began and MIIC emailed no one:
    # the claim is given back and the next run submits the school.
    mock_aisr.faults.puturl_status["2543"] = 500

    first = submit(make_ctx(bucket, tmp_path, mock_aisr, "run-1"))

    assert first.failed == frozenset({"2543"})
    assert mock_aisr.received_uploads == ["2542", "2544"]
    assert f"{period}_query_2543" not in claims(bucket)

    mock_aisr.faults.clear()
    mock_aisr.received_uploads.clear()
    second = submit(make_ctx(bucket, tmp_path, mock_aisr, "run-2"))

    assert second.submitted == frozenset(SCHOOL_IDS)
    assert not second.incomplete
    assert mock_aisr.received_uploads == ["2543"]
    assert_every_upload_was_claimed_by(bucket, ["2543"], "run-2", period)


def test_a_failed_upload_keeps_its_claim_and_is_never_resent(
    bucket, tmp_path, mock_aisr, period
):
    # The upload itself failed: MIIC may or may not have it, so the claim
    # stays held and the rerun reports the school stuck for a human.
    mock_aisr.faults.upload_status["2543"] = 500

    first = submit(make_ctx(bucket, tmp_path, mock_aisr, "run-1"))

    assert first.failed == frozenset({"2543"})
    assert claims(bucket)[f"{period}_query_2543"]["run_id"] == "run-1"

    mock_aisr.faults.clear()
    mock_aisr.received_uploads.clear()
    second = submit(make_ctx(bucket, tmp_path, mock_aisr, "run-2"))

    assert second.stuck == frozenset({"2543"})
    assert mock_aisr.received_uploads == []


def test_a_missing_roster_fails_before_anything_is_claimed(
    bucket, tmp_path, mock_aisr, period
):
    ctx = make_ctx(bucket, tmp_path, mock_aisr, "run-1")
    del bucket.objects[roster_path("2543")]

    result = submit(ctx)

    assert result.failed == frozenset({"2543"})
    assert f"{period}_query_2543" not in claims(bucket)
    assert mock_aisr.received_uploads == ["2542", "2544"]


def test_the_submitted_roster_is_the_one_in_the_bucket(bucket, tmp_path, mock_aisr):
    bucket.write(roster_path("2542"), "id_1|id_2\n81|91\n")
    ctx = make_ctx(bucket, tmp_path, mock_aisr, "run-1")

    submit(ctx)

    (event,) = [
        e for e in query_submitted_events(bucket) if e["data"]["school_id"] == "2542"
    ]
    assert event["data"]["query_file_hash"] == sha256_hex("id_1|id_2\n81|91\n")


def test_a_failed_login_leaves_no_claims(bucket, tmp_path, mock_aisr):
    ctx = make_ctx(bucket, tmp_path, mock_aisr, "run-1", password="wrong")

    with pytest.raises(AuthenticationError):
        submit(ctx)

    assert claims(bucket) == {}
    assert mock_aisr.received_uploads == []


def test_the_legacy_period_claim_counts_as_all_submitted(
    bucket, tmp_path, mock_aisr, period
):
    # Before per-school claims, one claim covered the whole period.
    bucket.write(
        f"ledger/claims/{period}_query",
        json.dumps({"run_id": "old-run", "at": "2026-10-01T07:09:00"}),
    )

    result = submit(make_ctx(bucket, tmp_path, mock_aisr, "run-1"))

    assert result.submitted == frozenset(SCHOOL_IDS)
    assert mock_aisr.received_uploads == []


def test_an_uncheckable_claim_fails_closed(bucket, tmp_path, mock_aisr, period):
    class FlakyClaims(GcsRunLedger):
        def claim(self, key):
            if key.endswith("_2544"):
                raise ConnectionError("storage blip")
            return super().claim(key)

    ctx = make_ctx(bucket, tmp_path, mock_aisr, "run-1", ledger_cls=FlakyClaims)

    result = submit(ctx)

    assert result.failed == frozenset({"2544"})
    assert mock_aisr.received_uploads == ["2542", "2543"]
    assert_every_upload_was_claimed_by(
        bucket, mock_aisr.received_uploads, "run-1", period
    )


def test_a_ledger_read_failure_raises_before_anything_is_claimed(
    bucket, tmp_path, mock_aisr
):
    class UnreadableLedger(GcsRunLedger):
        def recent_runs(self, months=2, limit=None):
            raise ConnectionError("storage down")

    ctx = make_ctx(bucket, tmp_path, mock_aisr, "run-1", ledger_cls=UnreadableLedger)

    with pytest.raises(ConnectionError):
        submit(ctx)

    assert claims(bucket) == {}
    assert mock_aisr.received_uploads == []
