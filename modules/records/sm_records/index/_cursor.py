"""Opaque keyset cursors for the record list — design §"F11".

``?page=N`` asks the database to produce and discard ``(N-1) x page_size``
rows before the ones it wants; the cost is linear in the rows skipped and is
paid again on every page. ``?after=<cursor>`` asks for "the rows the order
puts after this one" instead, which the same index that answers the ordering
answers directly. The three *internal* walks in this module
(``reindex_type``, ``_dry_run._batches``, ``_orphaned._records``) have always
paged this way; this is the same technique made available to a caller.

A cursor is **opaque but not secret**: base64 of a small JSON object, so a
client cannot read anything into its parts and a server can decode it without
storing anything. It carries two things.

*The sort values of the row it points at*, plus that row's ``id`` — the tuple
:func:`sm_records.index._sorting.keyset_clause` compares against.

*A signature of the sort it was produced under.* A cursor taken while sorting
by ``placed_at`` and replayed while sorting by ``price`` would compare a
timestamp against a decimal and skip an arbitrary part of the type; there is
no correct answer to give, so it is refused. The signature covers the type
key, the ordered ``(field, direction)`` list and whether the listing was the
trash, because each of those changes what the tuple means.

Every decode failure is one :class:`CursorError` and one 400: a malformed
cursor is a client bug, and distinguishing "not base64" from "wrong sort" for
the caller buys nothing.
"""

from __future__ import annotations

import base64
import binascii
import enum
import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sm_records.index._sorting import SortTerm
from sm_records.models import RecordStatus
from sm_records.schema.types import IndexKind

__all__ = ["CursorError", "decode_cursor", "encode_cursor", "sort_signature"]


class CursorError(ValueError):
    """A ``?after=`` value this listing cannot resume from."""


def sort_signature(type_key: str, sorts: Sequence[Any], *, trashed: bool = False) -> str:
    """A short, stable digest of "what order is this". See the module docstring.

    Truncated to 12 hex characters: it is a mismatch detector, not a MAC —
    nothing is authorised by it, and a forged one can only make the caller
    skip rows of a listing they were already allowed to read.
    """
    spec = json.dumps(
        {
            "t": type_key,
            "s": [[s.field, bool(s.desc)] for s in sorts],
            "x": bool(trashed),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(spec.encode()).hexdigest()[:12]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal | float):
        return str(value)
    return str(value)


def encode_cursor(signature: str, values: Sequence[Any]) -> str:
    """The cursor for a row whose sort values (plus ``id``) are ``values``."""
    raw = json.dumps(
        {"h": signature, "v": [_jsonable(v) for v in values]}, separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _as_datetime(raw: Any) -> datetime:
    return datetime.fromisoformat(str(raw))


def _as_date(raw: Any) -> date:
    return date.fromisoformat(str(raw))


_FIXED_DECODE: dict[str, Any] = {
    "status": RecordStatus,
    "position": int,
    "published_at": _as_datetime,
    "created_at": _as_datetime,
    "updated_at": _as_datetime,
    "display_title": str,
    "slug": str,
}

_KIND_DECODE: dict[IndexKind, Any] = {
    IndexKind.TEXT: str,
    IndexKind.NUMBER: Decimal,
    IndexKind.BOOL: bool,
    IndexKind.DATE: _as_date,
    IndexKind.DATETIME: _as_datetime,
    IndexKind.REF: str,
}


def _decode_value(term: SortTerm, raw: Any) -> Any:
    """Back to the Python value the *column* yielded, exactly.

    Deliberately **not** the filter grammar's coercers. Those read what a
    human typed and enforce rules on it — ``coerce_datetime`` refuses a naive
    timestamp, because a filter written without a zone is ambiguous. A cursor
    value was not typed by anybody: it came out of the column on the previous
    page and has to go back in unchanged, and SQLite hands back a naive
    ``datetime`` for a ``DateTime(timezone=True)`` column written without one.
    Coercing it the filter way turned every ``?after=`` over a datetime sort
    into a 400.

    JSON still has three scalar types where the columns have seven, so the
    conversion has to happen — it just has to be the identity on the round
    trip rather than a validation of it.
    """
    if raw is None:
        return None
    decode = _FIXED_DECODE[term.fixed] if term.fixed is not None else _KIND_DECODE[term.kind]
    try:
        return decode(raw)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise CursorError(f"cursor value {raw!r} is not valid for this sort") from exc


def decode_cursor(raw: str, signature: str, terms: Sequence[SortTerm]) -> list[Any]:
    """The value tuple ``raw`` carries, validated against this listing's sort.

    Returns ``len(terms) + 1`` values — one per sort term and the ``id``
    tiebreaker — ready for
    :func:`sm_records.index._sorting.keyset_clause`.
    """
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise CursorError("cursor is not a valid cursor") from exc
    if not isinstance(payload, dict) or payload.get("h") != signature:
        raise CursorError("cursor was produced under a different sort order")
    values = payload.get("v")
    if not isinstance(values, list) or len(values) != len(terms) + 1:
        raise CursorError("cursor does not match this sort order")
    decoded = [_decode_value(term, value) for term, value in zip(terms, values[:-1], strict=True)]
    try:
        decoded.append(int(values[-1]))
    except (TypeError, ValueError) as exc:
        raise CursorError("cursor carries no record id") from exc
    return decoded
