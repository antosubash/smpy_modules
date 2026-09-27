"""Opaque keyset cursors for the record list — design §"F11".

``?page=N`` asks the database to produce and discard ``(N-1) x page_size``
rows before the ones it wants; the cost is linear in the rows skipped and is
paid again on every page. ``?after=<cursor>`` asks for "the rows the order
puts after this one" instead, which the same index that answers the ordering
answers directly. The module's *internal* batched walks
(``services._common.walk_type``) have always paged this way; this is the
same technique made available to a caller.

A cursor is **opaque but not secret**: base64 of a small JSON object, so a
client cannot read anything into its parts and a server can decode it without
storing anything. It carries two things.

*The sort values of the row it points at*, plus that row's ``id`` — the tuple
:func:`sm_records.index._sorting.keyset_clause` compares against.

*A signature of the sort it was produced under.* A cursor taken while sorting
by ``placed_at`` and replayed while sorting by ``price`` would compare a
timestamp against a decimal and skip an arbitrary part of the type; there is
no correct answer to give, so it is refused. The signature covers everything
that changes what the tuple means: the type key, the ordered ``(field,
direction)`` list, whether the listing was the trash, **the sort fields'
resolved index kinds**, **the locale the listing was taken under** and **the
tenant it was taken in**.

The last two were added after a QA pass found them missing. A field retyped
from ``number`` to ``text`` between two pages of a walk leaves the same field
name in the cursor while ``"1.00000"`` stops being a decimal and starts being
a string, so the keyset comparison silently skips or repeats rows; the kinds
are what notice. And the public listing's ``?locale=`` is a predicate on the
statement rather than a caller filter (``services.public._narrow_for``), so a
cursor minted under ``?locale=en`` and replayed under ``?locale=de`` was
accepted — no leak, since the predicate still applies, but "resume after this
row" means nothing across two different listings.

The tenant (tenancy design §H) is read from the binding, never passed in, so
no caller can forget it. Two tenants may both have a type ``post``, so without
it a cursor minted in ``acme`` would be accepted in ``globex``. That was never
a leak — the listing's own tenant predicate still applies and the values
compared against are the caller's own rows — but "resume after this row" names
a row the caller cannot see, and the answer would be an arbitrary slice.

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
from sm_records.tenancy import bound_tenant

__all__ = ["CursorError", "decode_cursor", "encode_cursor", "sort_signature"]


class CursorError(ValueError):
    """A ``?after=`` value this listing cannot resume from."""


def _term_kinds(terms: Sequence[SortTerm]) -> list[str]:
    """How each resolved sort term's values are typed, as stable strings.

    ``fixed:<column>`` for a fixed column and the :class:`IndexKind` value for
    an indexed or virtual field — i.e. exactly what ``_decode_value`` picks its
    decoder by. Part of the signature, so retyping a field invalidates the
    cursors taken before it rather than comparing a decimal against a string.
    """
    return [f"fixed:{term.fixed}" if term.fixed is not None else term.kind.value for term in terms]


def sort_signature(
    type_key: str,
    sorts: Sequence[Any],
    *,
    trashed: bool = False,
    locale: str | None = None,
    terms: Sequence[SortTerm] = (),
) -> str:
    """A short, stable digest of "what order is this". See the module docstring.

    ``terms`` is the resolved sort (:func:`sort_plan`), read only for each
    term's value kind, and ``locale`` is the language a public listing was
    narrowed to — ``None`` on the admin listing, where a locale is an ordinary
    filter and filters are deliberately not part of a cursor. The bound
    tenant is always part of it; with none bound this raises
    :class:`~sm_records.tenancy.TenantUnbound`, as any records read would.

    Truncated to 12 hex characters: it is a mismatch detector, not a MAC —
    nothing is authorised by it, and a forged one can only make the caller
    skip rows of a listing they were already allowed to read.
    """
    spec = json.dumps(
        {
            "t": type_key,
            "s": [[s.field, bool(s.desc)] for s in sorts],
            "x": bool(trashed),
            "k": _term_kinds(terms),
            "l": locale,
            "n": bound_tenant(),
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
    # The grammar calls it ``invalid`` and the column is ``invalid_since``, a
    # timestamp — which is what a sort on it orders by, so that is what comes
    # back out of the row and has to go back in (``_fixed._FIXED_ALIAS``).
    "invalid": _as_datetime,
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
