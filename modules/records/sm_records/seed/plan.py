"""How many records of each type a seeding run writes.

Split out of :mod:`sm_records.seed.runner` for the 300-line cap, along the seam
that was already there: this module is the arithmetic of a run — the shares and
the rounding — and that one is the writing.
"""

from __future__ import annotations

import math

__all__ = ["distribute", "weights_for"]


#: Total record count is split across the five global types by these weights
#: (task spec: 5% / 25% / 15% / 45% / 10%), each type getting at least one
#: record regardless of how small ``records`` is.
WEIGHTS: dict[str, float] = {
    "company": 0.05,
    "contact": 0.25,
    "product": 0.15,
    "store": 0.10,
    "order": 0.45,
}

EVENT_WEIGHT = 0.05
"""``event``'s share on a host that declares the ``events`` collection.

Taken *proportionally* from the five above rather than added on top, so
``--records N`` still writes exactly N records whether or not a collection is
declared. On a host that declares none the five weights are used unchanged,
which is the arithmetic Phase 4 had (§6.5)."""


def weights_for(keys: set[str]) -> dict[str, float]:
    """The weight map for the types this process can create."""
    if "event" not in keys:
        return dict(WEIGHTS)
    scaled = {key: weight * (1 - EVENT_WEIGHT) for key, weight in WEIGHTS.items()}
    return {**scaled, "event": EVENT_WEIGHT}


def distribute(total: int, weights: dict[str, float]) -> dict[str, int]:
    """Split ``total`` across ``weights``' keys, each getting at least one.

    Largest-remainder rounding: floor every share, hand out the leftover to
    the keys with the biggest fractional part, and — for a ``total`` too
    small to give every key its floor plus its forced minimum of one — claw
    back from the keys least entitled to the extra. Exact for any
    ``total >= len(weights)``, which every sane invocation satisfies.
    """
    keys = list(weights)
    if total <= 0:
        return dict.fromkeys(keys, 0)
    if total < len(keys):
        return {key: (1 if i < total else 0) for i, key in enumerate(keys)}

    raw = {key: total * weight for key, weight in weights.items()}
    counts = {key: max(1, math.floor(raw[key])) for key in keys}
    diff = total - sum(counts.values())

    by_frac_desc = sorted(keys, key=lambda k: raw[k] - math.floor(raw[k]), reverse=True)
    by_frac_asc = list(reversed(by_frac_desc))
    i = 0
    while diff > 0:
        counts[by_frac_desc[i % len(keys)]] += 1
        diff -= 1
        i += 1
    i = 0
    while diff < 0:
        key = by_frac_asc[i % len(keys)]
        if counts[key] > 1:
            counts[key] -= 1
            diff += 1
        i += 1
    return counts
