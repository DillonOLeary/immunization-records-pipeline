"""Roster submission: every school's roster to the registry, at most once
per period, because each one emails every nurse in the district."""

from __future__ import annotations

import logging

from mn_immunization.records.hashing import sha256_hex
from mn_immunization.workflow import events
from mn_immunization.workflow.context import RunContext
from mn_immunization.workflow.policy import Submission
from mn_immunization.workflow.ports import RosterNotSentError
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
    pending = [school for school in ctx.schools if school.id not in submitted]
    if not pending:
        logger.info(
            "All rosters already submitted for period %s; nothing to send", period
        )
        return Submission(submitted=frozenset(submitted))

    stuck: set[str] = set()
    failed: set[str] = set()
    logger.info("Submitting %d roster(s) for period %s", len(pending), period)
    with ctx.open_registry() as registry:
        for school in pending:
            try:
                roster = ctx.objects.read_text(school.roster_path)
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
            append_event(
                ctx.ledger,
                events.query_submitted(
                    school_id=school.id,
                    query_file_hash=sha256_hex(roster),
                    period=period,
                ),
            )
    return Submission(
        submitted=frozenset(submitted),
        stuck=frozenset(stuck),
        failed=frozenset(failed),
    )


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
