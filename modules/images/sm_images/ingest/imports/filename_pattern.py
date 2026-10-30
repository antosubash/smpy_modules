"""User filename patterns: ``(?P<group>...)`` and an optional ``(?P<role>...)``.

Ported from the portal's ``grouping.py`` with the bag vocabulary renamed. A
pattern is a user's regular expression run against every imported filename, so
it is compiled and matched with the ``regex`` engine, which takes a per-match
**timeout**: a catastrophic pattern costs one feature its grouping, never a
worker. Validation (:func:`compile_pattern`) and execution use the same engine
and flags, so a pattern the API accepted is the pattern the worker runs.

A role is canonicalised against the collection's ``group_roles``: matched
case-insensitively and stored in the collection's own spelling; a role the
collection does not list is dropped (there is nobody to hand a 422 to at
import time). A collection with no roles keeps the role lowercased.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Sequence
from typing import Final

import regex

from sm_images.core import constants

__all__ = [
    "MATCH_TIMEOUT_SECONDS",
    "MAX_INPUT_LENGTH",
    "MAX_PATTERN_LENGTH",
    "PatternError",
    "canonical_role",
    "compile_pattern",
    "derive",
    "group_key",
    "match_group",
]

logger = logging.getLogger(__name__)

MAX_PATTERN_LENGTH: Final = 500
MAX_INPUT_LENGTH: Final = 1000
MATCH_TIMEOUT_SECONDS: Final = 0.05
_FLAGS: Final = regex.IGNORECASE | regex.VERSION0


class PatternError(ValueError):
    """The pattern is too long, does not compile, or names no ``group``."""


@functools.lru_cache(maxsize=64)
def _compiled(pattern: str) -> regex.Pattern[str]:
    return regex.compile(pattern, flags=_FLAGS)


def compile_pattern(pattern: str) -> regex.Pattern[str]:
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise PatternError("pattern_too_long")
    try:
        compiled = _compiled(pattern)
    except regex.error as exc:
        raise PatternError("pattern_invalid") from exc
    if "group" not in compiled.groupindex:
        raise PatternError("pattern_needs_group")
    return compiled


def group_key(raw: object) -> str | None:
    """A group key as text, trimmed; ``None`` when blank or too long for the column
    (truncating would merge distinct keys). ``0`` is a key; a boolean is not."""
    if raw is None or isinstance(raw, bool | dict | list):
        return None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    key = str(raw).strip()
    if not key or len(key) > constants.GROUP_KEY_MAX:
        return None
    return key


def canonical_role(raw: object, roles: Sequence[str]) -> str | None:
    if raw is None or isinstance(raw, bool | dict | list):
        return None
    role = str(raw).strip().lower()
    if not role:
        return None
    if roles:
        for known in roles:
            if known.lower() == role:
                return known
        return None
    return role if len(role) <= constants.GROUP_ROLE_MAX else None


TIMED_OUT: Final = "timed_out"
NO_MATCH: Final = "no_match"
MATCHED: Final = "matched"


def derive(
    compiled: regex.Pattern[str],
    filename: str,
    roles: Sequence[str],
    *,
    budget: float | None = None,
) -> tuple[str, str | None, str | None]:
    """``(outcome, group_key, role)`` of an already compiled pattern on ``filename``.

    The outcome tells a timeout from a plain non-match, which a regroup reports
    apart. ``group_key`` is ``None`` unless the outcome is ``matched``. ``budget``
    (seconds left of a caller's overall deadline) caps the per-match timeout.
    """
    if not filename or len(filename) > MAX_INPUT_LENGTH:
        return NO_MATCH, None, None
    try:
        timeout = MATCH_TIMEOUT_SECONDS if budget is None else min(MATCH_TIMEOUT_SECONDS, budget)
        found = compiled.match(filename, timeout=timeout)
    except TimeoutError:
        logger.warning("images.import.pattern_timeout filename=%s", filename[:200])
        return TIMED_OUT, None, None
    if found is None:
        return NO_MATCH, None, None
    parts = found.groupdict()
    key = group_key(parts.get("group"))
    if key is None:
        return NO_MATCH, None, None
    return MATCHED, key, canonical_role(parts.get("role"), roles)


def match_group(pattern: str, filename: str, roles: Sequence[str]) -> tuple[str | None, str | None]:
    """``(group_key, role)`` the pattern derives from ``filename``; ``(None, None)``
    for no match, an over-long input, an invalid pattern or a timeout."""
    try:
        compiled = compile_pattern(pattern)
    except PatternError:
        return None, None
    _, key, role = derive(compiled, filename, roles)
    return key, role
