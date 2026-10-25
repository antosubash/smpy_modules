"""The ``text``-like length and pattern checks, split from ``_builders`` for
the 300-line cap.

Patterns are Python ``re`` patterns, matched with ``re`` — the engine the
save-time check compiles them with, so a constraint means exactly what it has
always meant. Matching a value somebody sent must not happen here, on the
event loop (``re`` cannot be interrupted): the write paths check every
patterned value first in a worker process under a deadline
(:mod:`sm_records.services._patterns`) and validate inside :func:`checked`,
which hands this check the **verdicts** for exactly the ``(pattern, value)``
pairs that were checked. A pair with a verdict is decided by it; on a write
any other pair is matched here as before — nothing is switched off
wholesale. Only the read path, inside :func:`reading`, leaves a pair without
a verdict unmatched.

Keyed by the pattern's source rather than the field key: the verdict is a
function of the pattern and the value alone, and the pattern is what this
check holds. Two fields sharing a pattern and a value share one verdict,
which is the same answer either would get.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

__all__ = ["Verdicts", "checked", "reading", "text_check", "verdicts"]

Verdicts = Mapping[tuple[str, str], bool]
"""``{(pattern source, value): matched}``."""

_VERDICTS: ContextVar[Verdicts | None] = ContextVar("sm_records_pattern_verdicts", default=None)
_READING: ContextVar[bool] = ContextVar("sm_records_pattern_reading", default=False)


def verdicts() -> Verdicts:
    """The verdicts in scope here."""
    return _VERDICTS.get() or {}


@contextmanager
def checked(found: Verdicts) -> Iterator[None]:
    """Validate inside with ``found`` added to the verdicts in scope."""
    token = _VERDICTS.set({**verdicts(), **found})
    try:
        yield
    finally:
        _VERDICTS.reset(token)


@contextmanager
def reading() -> Iterator[None]:
    """The read path: a pattern with no verdict is not matched at all.

    Reads never write, and a read must never run an unbounded match on the
    loop — a list page would run one per row. The lenient read
    (``compile.from_stored``) hands back the stored string whether or not it
    matches, so its output does not depend on the pattern; the editor's
    ``invalid`` badge (``_payload.read_view``) reports a pattern only where a
    verdict is in scope. Pattern violations are refused on every write, and
    found in stored records by a schema change's checked scan.
    """
    token = _READING.set(True)
    try:
        yield
    finally:
        _READING.reset(token)


def text_check(constraints: dict[str, Any], *, required: bool = False):
    minimum = constraints.get("min_length")
    maximum = constraints.get("max_length")
    source = constraints.get("pattern") or None
    pattern = re.compile(source) if source else None

    def check(value: str | None) -> str | None:
        if value is None:
            return None
        # ``required`` alone means "present and not null", which left ``""``
        # satisfying a field the form marks with an asterisk.
        if required and not value.strip():
            raise ValueError("this field is required")
        if minimum is not None and len(value) < minimum:
            raise ValueError(f"must be at least {minimum} characters")
        if maximum is not None and len(value) > maximum:
            raise ValueError(f"must be at most {maximum} characters")
        if pattern is not None and source is not None:
            verdict = verdicts().get((source, value))
            if verdict is None:
                verdict = True if _READING.get() else pattern.search(value) is not None
            if not verdict:
                raise ValueError(f"must match {source}")
        return value

    return check
