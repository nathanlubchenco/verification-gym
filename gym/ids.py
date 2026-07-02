"""Opaque identifiers. Ids must never encode arm, class, or any ground-truth
signal (HANDOFF §5 blindness): hex alphabet only, so no forbidden word can occur
except hex-spellable ones, which we exclude by rejection sampling."""

from __future__ import annotations

import random

# lowercase substrings that must never appear in an id (checked in tests and
# enforced by rejection sampling below; hex can spell e.g. "dead", "bad").
FORBIDDEN_ID_SUBSTRINGS = (
    "mut", "gen", "szz", "clean", "canary", "defect", "bug", "bad", "fault",
)


def make_id(prefix: str, rng: random.Random, nhex: int = 10) -> str:
    while True:
        body = "".join(rng.choice("0123456789abcdef") for _ in range(nhex))
        if not any(bad in body for bad in FORBIDDEN_ID_SUBSTRINGS):
            return f"{prefix}-{body}"
