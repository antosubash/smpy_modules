"""The value a new ``tags`` choice gets from its label (newsletter PR 7, D8). Pure.

Moved here from newsletter (Codex finding 4) so :func:`.campaign_lists.add_choices`
can decide every value under the list's type lock, against the choices as they
are then; newsletter's staging preview calls the same rule through the contract
(``tag_choice_values``).

A label is reused when a choice already carries it; else it is its own value,
unless it holds a comma or another choice holds that value; else the slug plus
a hash, with ``-2``, ``-3``… while that is taken too. Labels are resolved in
sorted order, so the answer is deterministic.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

__all__ = ["tag_values"]


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-") or "tag"


def _fallback(label: str, taken: set[str]) -> str:
    base = f"{_slug(label)[:80]}-{hashlib.sha256(label.encode()).hexdigest()[:8]}"
    value, n = base, 1
    while value in taken:
        n += 1
        value = f"{base}-{n}"
    return value


def tag_values(labels: Iterable[str], existing: Sequence[tuple[str, str]]) -> dict[str, str]:
    """Label to choice value, given the list's ``(value, label)`` choices."""
    by_label: dict[str, str] = {}
    for value, label in existing:
        by_label.setdefault(label, value)
    taken = {value for value, _ in existing}
    result: dict[str, str] = {}
    for label in sorted(set(labels)):
        if label in by_label:
            result[label] = by_label[label]
        elif "," not in label and label not in taken:
            result[label] = label
        else:
            result[label] = _fallback(label, taken)
        taken.add(result[label])
    return result
