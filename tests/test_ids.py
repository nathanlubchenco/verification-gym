"""Opaque ids must be deterministic per seed and leak nothing (arm/class names)."""

import random

from gym.ids import FORBIDDEN_ID_SUBSTRINGS, make_id


def test_deterministic_for_seed():
    a = [make_id("it", random.Random(42)) for _ in range(5)]
    b = [make_id("it", random.Random(42)) for _ in range(5)]
    assert a == b


def test_distinct_and_prefixed():
    rng = random.Random(1)
    ids = {make_id("d", rng) for _ in range(1000)}
    assert len(ids) == 1000
    assert all(i.startswith("d-") for i in ids)


def test_no_forbidden_substrings():
    rng = random.Random(7)
    for _ in range(2000):
        i = make_id("it", rng).lower()
        for bad in FORBIDDEN_ID_SUBSTRINGS:
            assert bad not in i, f"{bad!r} in {i}"
