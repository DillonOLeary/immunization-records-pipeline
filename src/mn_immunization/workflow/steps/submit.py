"""Roster submission: every school's roster to the registry, at most once
per period, because each one emails every nurse in the district."""

from __future__ import annotations

import logging

from mn_immunization.records.hashing import sha256_hex
from mn_immunization.records.roster import RosterFormatError, check_roster
from mn_immunization.workflow import events
from mn_immunization.workflow.context import RunContext
from mn_immunization.workflow.layout import roster_path
from mn_immunization.workflow.policy import Submission
from mn_immunization.workflow.ports import (
    ObjectNotFoundError,
    RosterNotSentError,
    School,
)
from mn_immunization.workflow.support import append_event

logger = logging.getLogger(__name__)


def query_period(ctx: RunContext) -> str:
    """The period this execution works on: one roster submission per
    school per period."""
    return ctx.period


def submit_queries(ctx: RunContext) -> Submission:
    """Submit each school's roster at most once per period. Fails closed.

    Every submission makes MIIC email every nurse in the district, so a
    roster that may already have gone out is never sent again:

    - a school with a QuerySubmitted event this period is done;
    - otherwise its per-school claim `<period>_query_<school_id>` is taken
      just before its upload; a lost claim with no event means an earlier
      run may have uploaded and then failed to record it, so the school is
      `stuck`: skipped, and the run will fail loudly for a human to check;
    - a claim that cannot even be checked is `failed`, with nothing sent
      (this is the one claim that fails closed: here, acting twice is the
      failure that matters);
    - an upload that raises is `failed`; if it failed before anything was
      uploaded (RosterNotSentError), its claim is released so a rerun can
      submit it, since MIIC received nothing;
    - a roster that cannot be read from the bucket is `failed` before
      anything is claimed.

    First, when the district has a roster source (Infinite Campus), each
    pending school's roster is exported fresh and put on file
    (`refresh_rosters`); one that cannot be is sent as it was on file and
    marked `stale`, so the period still delivers but ends failed.

    Ledger reads happen before anything is claimed, and login before any
    claim too, so a read error or a failed login leaves no claims behind.
    """
    period = query_period(ctx)
    prefix = f"{period}_query"
    history = ctx.history()
    held = ctx.ledger.held_claims(prefix)
    all_ids = {school.id for school in ctx.schools}

    if prefix in held:
        # The period-wide claim from before per-school claims: the whole
        # period's rosters went out under it.
        logger.info("Period %s was submitted under the legacy claim", period)
        return Submission(submitted=frozenset(all_ids))

    submitted = set(history.submissions(period)) & all_ids
    stale = history.stale_rosters(period) & all_ids
    pending = [school for school in ctx.schools if school.id not in submitted]
    if not pending:
        logger.info(
            "All rosters already submitted for period %s; nothing to send", period
        )
        return Submission(submitted=frozenset(submitted), stale=frozenset(stale))

    origin = refresh_rosters(ctx, pending)

    stuck: set[str] = set()
    failed: set[str] = set()
    logger.info("Submitting %d roster(s) for period %s", len(pending), period)
    with ctx.open_registry() as registry:
        for school in pending:
            try:
                roster = ctx.objects.read_text(roster_path(school.id))
            except Exception as error:
                failed.add(school.id)
                logger.error(
                    "Roster for %s could not be read (%s); not submitting",
                    school.name,
                    type(error).__name__,
                )
                continue
            key = f"{prefix}_{school.id}"
            try:
                won = ctx.ledger.claim(key)
            except Exception as error:
                failed.add(school.id)
                logger.error(
                    "Claim check failed for %s (%s); not submitting",
                    school.name,
                    type(error).__name__,
                )
                continue
            if not won:
                stuck.add(school.id)
                logger.error(
                    "Roster for %s is claimed but not recorded as submitted "
                    "this period; skipping it (see ONBOARDING: stuck claims)",
                    school.name,
                )
                continue
            try:
                registry.submit_roster(school, roster)
            except Exception as error:
                failed.add(school.id)
                logger.error(
                    "Bulk query failed for %s: %s (HTTP %s)",
                    school.name,
                    type(error).__name__,
                    getattr(error, "status_code", None),
                )
                if isinstance(error, RosterNotSentError):
                    _release_unsent(ctx, key, school.name)
                continue
            submitted.add(school.id)
            if origin[school.id] == "stale":
                stale.add(school.id)
            append_event(
                ctx.ledger,
                events.query_submitted(
                    school_id=school.id,
                    query_file_hash=sha256_hex(roster),
                    period=period,
                    roster=origin[school.id],
                ),
            )
    return Submission(
        submitted=frozenset(submitted),
        stuck=frozenset(stuck),
        failed=frozenset(failed),
        stale=frozenset(stale),
    )


def refresh_rosters(ctx: RunContext, schools: list[School]) -> dict[str, str]:
    """Export each school's roster fresh from the roster source and put it
    on file, so the submission sends it. Returns school id -> "exported",
    "stale" (the export failed or was unfit, so the roster on file goes
    instead), or "on_file" (no roster source is configured).

    A fresh roster replaces the one on file only if `check_roster` passes:
    the MIIC layout, and not under half the students it had. Roster
    content never reaches a log; only counts, classes, and problems do.
    """
    if ctx.open_rosters is None:
        return {school.id: "on_file" for school in schools}
    origin = {school.id: "stale" for school in schools}
    try:
        with ctx.open_rosters() as source:
            for school in schools:
                try:
                    roster = source.export_roster(school.id)
                    count = check_roster(roster, _on_file(ctx, school.id))
                    ctx.objects.write_text(roster_path(school.id), roster, "text/csv")
                except Exception as error:
                    logger.error(
                        "Roster export for %s failed (%s%s); sending the roster "
                        "on file",
                        school.name,
                        type(error).__name__,
                        f": {error.problem}"
                        if isinstance(error, RosterFormatError)
                        else "",
                    )
                    continue
                origin[school.id] = "exported"
                logger.info("Exported roster for %s: %d students", school.name, count)
    except Exception as error:
        logger.error(
            "Could not reach the roster source (%s); sending the rosters on file",
            type(error).__name__,
        )
    return origin


def check_roster_exports(ctx: RunContext) -> tuple[int, int]:
    """The canary's look at the roster source: export every school's roster
    and check it as `refresh_rosters` would, keeping nothing. Returns
    (schools checked, exports that failed or were unfit)."""
    assert ctx.open_rosters is not None
    failed = 0
    try:
        with ctx.open_rosters() as source:
            for school in ctx.schools:
                try:
                    count = check_roster(
                        source.export_roster(school.id), _on_file(ctx, school.id)
                    )
                except Exception as error:
                    failed += 1
                    logger.error(
                        "Roster export for %s would fail (%s)",
                        school.name,
                        type(error).__name__,
                    )
                    continue
                logger.info("Roster export for %s: %d students", school.name, count)
    except Exception as error:
        logger.error("Could not reach the roster source (%s)", type(error).__name__)
        return len(ctx.schools), len(ctx.schools)
    return len(ctx.schools), failed


def _on_file(ctx: RunContext, school_id: str) -> str | None:
    try:
        return ctx.objects.read_text(roster_path(school_id))
    except ObjectNotFoundError:
        return None


def _release_unsent(ctx: RunContext, key: str, school_name: str) -> None:
    """The upload never began, so MIIC emailed no one: give the claim back
    and a rerun submits the school. If the release itself fails, the
    claim stays held and the school shows as stuck, which is safe."""
    try:
        ctx.ledger.release(key)
    except Exception as error:
        logger.warning(
            "Could not release the claim for %s (%s); it will show as stuck",
            school_name,
            type(error).__name__,
        )
        return
    logger.info(
        "Roster for %s was never sent; claim released, a rerun will submit it",
        school_name,
    )
