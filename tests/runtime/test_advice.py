"""Every failure tells its human what happened and what to do, in words
built only from error classes, steps, and school ids."""

import pytest

from mn_immunization.runtime.advice import BY_ERROR, advise


@pytest.mark.parametrize("error", sorted(BY_ERROR))
def test_every_known_error_has_a_headline_a_fix_and_the_status_command(error):
    headline, fix = advise({"status": "failed", "error": error, "step": "x"}, "b")
    assert headline and fix
    assert "mn-immunization status --bucket b" in fix


def test_an_expired_miic_password_says_which_secrets_to_update():
    headline, fix = advise({"error": "AuthenticationError", "step": "canary"}, "b")
    assert headline == "MIIC refused the pipeline's login"
    assert "miic-username" in fix and "miic-password" in fix


def test_stuck_and_stale_schools_are_named():
    _, fix = advise(
        {
            "error": "QuerySubmissionIncomplete",
            "stuck_schools": ["887"],
            "failed_schools": [],
        },
        "b",
    )
    assert "Stuck (claimed, unconfirmed): 887" in fix
    _, fix = advise(
        {"error": "RosterRefreshFailed", "stale_schools": ["2542", "891"]}, "b"
    )
    assert "2542, 891" in fix


def test_a_drive_failure_is_recognized_by_its_step():
    headline, _ = advise({"error": "HttpError", "step": "deliver_diff"}, "b")
    assert headline == "Delivering to Drive failed"


def test_anything_else_still_gets_a_headline_naming_the_class_and_step():
    headline, fix = advise({"error": "KeyError", "step": "compute_diff"}, "b")
    assert headline == "The pipeline failed (KeyError at compute_diff)"
    assert "rerun run" in fix
