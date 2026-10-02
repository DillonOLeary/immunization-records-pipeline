"""Where the workflow keeps things in the district's object store.

The store is a cache: the PHI here (rosters, the known set) can be
rebuilt, from IC and from MIIC (`refresh`). Only the ledger (no PHI) and
the config are worth keeping, plus the current period's roster claims:
lose those mid-period and the next run resends every roster.
"""

from __future__ import annotations

KNOWN_RECORDS = "known/records.csv"
"""Every record already delivered, in IC format: the only PHI kept."""

KNOWN_MARKER = "known/committed.json"
"""Written by every commit (a count and a hash, no PHI). Present without
KNOWN_RECORDS means the cache was lost, not that this is a first run."""


def roster_path(school_id: str) -> str:
    """A school's latest roster."""
    return f"rosters/{school_id}.csv"
