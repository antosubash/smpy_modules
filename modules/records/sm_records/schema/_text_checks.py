"""The ``text``-like length and pattern checks, split from ``_builders`` for
the 300-line cap.

Patterns are Python ``re`` patterns, matched with ``re`` — the same engine the
save-time check compiles them with, so a constraint means exactly what it has
always meant. ``re`` cannot be interrupted, and ``_sre`` holds the GIL for a
whole match, so an admin's ``^(a+)+$`` and an attacker's ``aaaa…!`` would pin
the event loop. Input from a website visitor therefore never reaches the
match here: :mod:`sm_records.public_submissions.patterns` checks it first in
a worker process under one deadline for the whole submission, and the writes
that follow run inside :func:`patterns_prechecked`, which skips the match
(the value was checked — or it is a stored value that already was).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

__all__ = ["patterns_prechecked", "text_check"]

_PRECHECKED: ContextVar[bool] = ContextVar("sm_records_patterns_prechecked", default=False)


@contextmanager
def patterns_prechecked() -> Iterator[None]:
    """Skip ``constraints.pattern`` inside the block: the caller has checked
    every value it writes against it already (off the event loop)."""
    token = _PRECHECKED.set(True)
    try:
        yield
    finally:
        _PRECHECKED.reset(token)


def text_check(constraints: dict[str, Any], *, required: bool = False):
    minimum = constraints.get("min_length")
    maximum = constraints.get("max_length")
    pattern = re.compile(constraints["pattern"]) if constraints.get("pattern") else None

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
        if pattern is not None and not _PRECHECKED.get() and not pattern.search(value):
            raise ValueError(f"must match {pattern.pattern}")
        return value

    return check
