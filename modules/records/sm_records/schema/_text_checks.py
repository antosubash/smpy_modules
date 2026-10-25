"""The ``text``-like length and pattern checks, split from ``_builders`` for
the 300-line cap — and because the pattern match is the one place a check has
to be bounded in *time*, not only in size (#101).
"""

from __future__ import annotations

from typing import Any

import regex

__all__ = ["PATTERN_TIMEOUT_SECONDS", "text_check"]

PATTERN_TIMEOUT_SECONDS = 0.1
"""How long one ``constraints.pattern`` match may run. An admin-written
pattern can backtrack catastrophically (``^(a+)+$``), and a website visitor
chooses the input (#101): a synchronous ``re`` match would pin the event loop.
``regex`` honours a timeout inside the matcher, and running out of it is the
same refusal as not matching."""


def _compile_pattern(source: str) -> Any:
    try:
        return regex.compile(source)
    except regex.error:
        # Valid for ``re`` (the save-time check) but not for ``regex``: refuse
        # every value rather than match it with an unbounded engine.
        return None


def text_check(constraints: dict[str, Any], *, required: bool = False):
    minimum = constraints.get("min_length")
    maximum = constraints.get("max_length")
    source = constraints.get("pattern") or None
    pattern = _compile_pattern(source) if source else None

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
        if source is not None and not _matches(pattern, value):
            raise ValueError(f"must match {source}")
        return value

    return check


def _matches(pattern: Any, value: str) -> bool:
    if pattern is None:
        return False
    try:
        return pattern.search(value, timeout=PATTERN_TIMEOUT_SECONDS) is not None
    except TimeoutError:
        return False
