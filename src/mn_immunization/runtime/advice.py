"""What a failed execution tells its human: one headline, one fix.

`job.main` adds these to the failed result line it prints, and a
log-based alert (infra alerts.tf) emails them: the headline becomes the
subject, the fix the body. Built only from error classes, step names,
and school ids, so nothing here can carry PHI. Every failure needs a
human (a failed period stays closed until `run` reopens it), so every
failure gets advice; anything unrecognized gets the generic kind.
"""

from __future__ import annotations

RERUN = (
    "gcloud run jobs execute pipeline-job --args=run,--trigger,manual "
    "--region us-central1 --project <project>"
)

BY_ERROR: dict[str, tuple[str, str]] = {
    "AuthenticationError": (
        "MIIC refused the pipeline's login",
        "The MIIC account's password has expired or the account was disabled. "
        "Put working credentials in the miic-username and miic-password "
        "secrets, then run the canary. If a period failed, rerun run: it never "
        "sends a roster twice.",
    ),
    "LoginUnavailableError": (
        "MIIC's login was down past the deadline",
        "MIIC answered with server errors until the period's deadline. Check "
        "AISR in a browser; once it works, rerun run.",
    ),
    "IcLoginError": (
        "Infinite Campus refused the pipeline's login",
        "Rosters can't be exported, so the ones on file would go to MIIC "
        "(missing new students). Check the infinite-campus-username and "
        "infinite-campus-password secrets, then run the canary.",
    ),
    "RosterCheckFailed": (
        "Roster exports from Infinite Campus aren't working",
        "The canary couldn't export a valid roster for every school. Check the "
        "infinite-campus-* secrets, that the saved MIIC filter still exists in "
        "Data Export, and the schools' calendars, then run the canary.",
    ),
    "StagingCheckFailed": (
        "MIIC isn't listing some schools' results",
        "The canary couldn't list results for every school. Usually temporary: "
        "if the next canary fails too, check the schools in AISR.",
    ),
    "NoQueriesSubmitted": (
        "No rosters could be sent to MIIC",
        "Every school failed or is stuck, so nothing went out and nurses got "
        "nothing. Run status for the schools and why, then rerun run.",
    ),
    "NoResultsStaged": (
        "MDH returned no results within 20 hours",
        "Rosters went out but no results came back. Check the schools in AISR; "
        "once results are listed, rerun run (it won't resend rosters).",
    ),
    "AllDownloadsFailed": (
        "MIIC's results files couldn't be read",
        "Every school's results failed to download or parse, which usually "
        "means MIIC changed its file format. The parser needs updating; nothing "
        "was delivered or committed.",
    ),
    "KnownRecordsMissingError": (
        "The record of what's already delivered is missing",
        "known/records.csv is gone though a commit happened, so the run stopped "
        "rather than redeliver everything. Run refresh to rebuild it from MIIC "
        "(it delivers every record once).",
    ),
    "IcFormatError": (
        "The record of what's already delivered is corrupt",
        "known/records.csv has a malformed row. Run refresh to rebuild it.",
    ),
    "SuspiciousDiffVolume": (
        "The brake stopped an unusually large delivery",
        "The diff was over 20% of every known record, which looks like a lost "
        "cache rather than new shots, so nothing was delivered. Check known/; if "
        "the records are genuine, run once with DIFF_SANITY_FRACTION=off.",
    ),
    "NoDriveFolder": (
        "No Drive folder is configured",
        "Set google_drive_folder_id in infra/districts/<district>.json and "
        "apply, then rerun run.",
    ),
    "FetchFailed": (
        "Refresh couldn't fetch every school",
        "Nothing was delivered or replaced. Run refresh again later.",
    ),
}

BY_STEP: dict[str, tuple[str, str]] = {
    "deliver_diff": (
        "Delivering to Drive failed",
        "Nothing is lost: the known set was left alone. Check that the "
        "'Immunization Records' folder exists and the drive-* secrets still "
        "work (infra/scripts/setup_google_drive_oauth.py), then rerun run: it "
        "sends only the files that are missing.",
    ),
}


def advise(result: dict, bucket: str) -> tuple[str, str]:
    """(headline, what to do) for a failed result."""
    error, step = result.get("error", ""), result.get("step", "")
    status = f"Details: uv run mn-immunization status --bucket {bucket}"

    if error == "QuerySubmissionIncomplete":
        stuck, failed = (
            result.get("stuck_schools", []),
            result.get("failed_schools", []),
        )
        return (
            "A school's roster may not have reached MIIC",
            f"Stuck (claimed, unconfirmed): {', '.join(stuck) or 'none'}. Failed: "
            f"{', '.join(failed) or 'none'}. Everyone else's records were "
            "delivered. Failed schools go out on a rerun of run. For stuck ones, "
            "ask whether MIIC got the roster; status prints the release command "
            f"for those that didn't (ONBOARDING: stuck claims). {status}",
        )
    if error == "RosterRefreshFailed":
        stale = ", ".join(result.get("stale_schools", [])) or "some schools"
        return (
            "Some rosters went out without this month's new students",
            f"Infinite Campus exports failed for school(s) {stale}, so their "
            "previous rosters were sent; all records were delivered. Fix IC (the "
            "infinite-campus-* secrets, the MIIC filter, calendars) before the "
            f"next period. No rerun needed. {status}",
        )
    headline, fix = (
        BY_ERROR.get(error)
        or BY_STEP.get(step)
        or (
            f"The pipeline failed ({error or 'unknown error'} at {step or 'startup'})",
            f"Look at the last run, fix the cause, then rerun run: {RERUN}.",
        )
    )
    return headline, f"{fix} {status}"
