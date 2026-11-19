"""One spelling of a user id for what a user owns, and every spelling a cleanup must match.

The framework's events carry a user id as a ``uuid.UUID`` or as text in any of its spellings
(hyphenated, bare hex, upper case, braced, ``urn:uuid:``), while a principal carries a string.
Rows written for a user (a follow) store :func:`canonical_user_id`, so one person is one value
whatever spelling the request had; a **cleanup** never relies on that: it matches
:func:`spellings` with ``lower(column)``, so a row in any spelling goes with its user. Ids that
are not UUIDs (an identity provider's) are left exactly as they are.
"""

from __future__ import annotations

import uuid
from typing import Any

__all__ = ["canonical_user_id", "spellings"]


def _as_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def canonical_user_id(value: Any) -> str:
    """Lower-case hyphenated for a UUID in any spelling, else the id unchanged."""
    parsed = _as_uuid(value)
    return str(parsed) if parsed is not None else str(value)


def spellings(value: Any) -> tuple[str, ...]:
    """Every lower-case form a stored id could hold; compare with ``lower(column)``."""
    parsed = _as_uuid(value)
    if parsed is not None:
        return (str(parsed), parsed.hex)
    text = str(value).lower()
    return tuple(dict.fromkeys((text, text.replace("-", ""))))
