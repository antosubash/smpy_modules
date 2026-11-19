"""One spelling of a user id for what a user owns, and every spelling a cleanup must match.

The framework's events carry a user id as a ``uuid.UUID`` or as text in any of its spellings
(hyphenated, bare hex, upper case, braced, ``urn:uuid:``), while a principal carries a string.
Rows written for a user (a follow) store :func:`canonical_user_id`, so one person is one value
whatever spelling the request had. A **cleanup** never relies on that: for a UUID it matches
every spelling (:func:`user_match`), so a row in any spelling goes with its user. Any other id
(an identity provider's) is left exactly as it is and matched exactly, so ``Bob`` and ``bob`` are
two people. A **read** compares to :func:`canonical_user_id` exactly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func

__all__ = ["canonical_user_id", "spellings", "user_match"]


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
    """The forms one identity can be stored in. Only a UUID has alternatives (case, dashes,
    braces and ``urn:`` are the same UUID); any other id is exactly itself, so ``Bob`` and ``bob``,
    ``a-b`` and ``ab`` are different people and nothing here ever folds them together."""
    parsed = _as_uuid(value)
    if parsed is not None:
        return (str(parsed), parsed.hex)
    return (str(value),)


def user_match(column: Any, value: Any) -> Any:
    """The SQL condition "this row's id column is this user", for a **write or delete** that must
    also catch rows stored in another spelling of a UUID: ``lower(column)`` against the UUID's two
    lower-case forms, and an exact comparison for any other id. Reads compare to
    :func:`canonical_user_id` exactly instead, which is what every row is written with."""
    if _as_uuid(value) is not None:
        return func.lower(column).in_(spellings(value))
    return column == str(value)
