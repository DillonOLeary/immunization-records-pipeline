"""Content hashing for ledger events: sha256 of text, as hex.

Events record hashes, never content, so a run's inputs and outputs can be
matched and reproduced without a record ever entering the ledger.
"""

from __future__ import annotations

import hashlib


def sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
