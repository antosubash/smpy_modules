"""Argument checks of the registration contract: strict, cheap, and before any query.

A malformed argument raises ``ValueError`` and nothing has touched the database. Ids are the
canonical lower-case spelling only (an occurrence key is embedded in a signed token and in a
unique index, so one value has one spelling); an occurrence key is an event uuid, optionally
followed by ``:YYYYMMDDTHHMMSSZ``, a real instant.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sm_events.core import constants
from sm_events.core.user_ids import canonical_user_id

__all__ = [
    "bounded_int",
    "event_id",
    "holder",
    "holders",
    "occurrence_key",
    "parse_stamp",
    "text",
]

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_EVENT_ID = re.compile(rf"^{_UUID}$")
_KEY = re.compile(rf"^(?P<id>{_UUID})(?::(?P<stamp>\d{{8}}T\d{{6}}Z))?$")


def event_id(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str) and _EVENT_ID.fullmatch(value):
        return uuid.UUID(value)
    raise ValueError("event_id must be an event uuid")


def parse_stamp(stamp: str) -> datetime:
    """The UTC instant of a key's ``YYYYMMDDTHHMMSSZ`` (``ValueError`` for an impossible one)."""
    return datetime.strptime(stamp, constants.OCCURRENCE_KEY_STAMP).replace(tzinfo=UTC)


def occurrence_key(value: Any) -> str:
    """``"{event_id}"`` or ``"{event_id}:{stamp}"``, at most ``OCCURRENCE_KEY_MAX`` characters."""
    if not isinstance(value, str) or len(value) > constants.OCCURRENCE_KEY_MAX:
        raise ValueError("occurrence_key is not an occurrence key")
    found = _KEY.fullmatch(value)
    if found is None:
        raise ValueError("occurrence_key is not an occurrence key")
    if found["stamp"] is not None:
        parse_stamp(found["stamp"])  # ValueError: an impossible date is malformed, not absent
    return value


def text(value: Any, name: str, *, maximum: int) -> str:
    """A non-empty, printable, single-line string of at most ``maximum`` characters."""
    if not isinstance(value, str) or not value or len(value) > maximum or not value.isprintable():
        raise ValueError(f"{name} must be a printable string of 1 to {maximum} characters")
    return value


def holder(value: Any) -> str:
    """A seat's holder, as it is stored: UUID spellings fold to one, anything else is exact."""
    return canonical_user_id(text(value, "holder", maximum=constants.REGISTRATION_HOLDER_MAX))


def holders(values: Any, *, maximum: int) -> list[str]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise ValueError("holders must be a sequence")
    if not 1 <= len(values) <= maximum:
        raise ValueError(f"holders must hold 1 to {maximum} ids")
    return list(dict.fromkeys(holder(v) for v in values))


def bounded_int(value: Any, name: str, *, low: int, high: int) -> int:
    """An int (a ``bool`` is not one) in ``[low, high]``."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value
