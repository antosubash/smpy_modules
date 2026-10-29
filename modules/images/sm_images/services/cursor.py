"""An opaque ``(created_at, id)`` keyset cursor.

Newest first, ties broken by id. The cursor names a *position*, not a row, so
it keeps working after the row it was cut from is deleted - an offset would
skip or repeat. Opaque on purpose: clients carry it, they do not build it.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_

from sm_images import constants
from sm_images.errors import Invalid

__all__ = ["cut", "decode", "encode", "seek"]

_SEP = "|"


def encode(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}{_SEP}{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stamp, _, ident = base64.urlsafe_b64decode(padded).decode().partition(_SEP)
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:  # a forged cursor must not reach timestamptz naive
            moment = moment.replace(tzinfo=UTC)
        return moment, uuid.UUID(ident)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise Invalid(constants.BAD_CURSOR_DETAIL) from exc


def seek(created_col: Any, id_col: Any, cursor: str) -> Any:
    """``WHERE`` clause for the rows strictly after *cursor* in
    ``(created_at DESC, id DESC)`` order."""
    created, ident = decode(cursor)
    return or_(created_col < created, and_(created_col == created, id_col < ident))


def cut(
    rows: list[Any], limit: int, *, last: Callable[[Any], Any] = lambda row: row
) -> tuple[list[Any], str | None]:
    """The page of a ``LIMIT limit + 1`` keyset query, and the cursor after it
    (``None`` on the last page). ``last`` picks the ``created_at``/``id``
    carrier out of a row."""
    more = len(rows) > limit
    rows = rows[:limit]
    if not more:
        return rows, None
    end = last(rows[-1])
    return rows, encode(end.created_at, end.id)
