"""Turning a stored or supplied value into the type its index column holds.

Shared by the index writer and the query builder on purpose: a filter that
coerced ``"12.50"`` differently from the provider that indexed it would
silently miss rows, and that is the failure mode this whole layer exists to
avoid. One function per index kind, and every one of them returns ``None``
rather than raising — "this value has no place in this table" is a normal
answer on the write path (design doc §8.4: a value that fails coercion is
simply absent from the index). The query builder turns the same ``None`` into
a ``QueryError``, because a filter the caller *typed* is a different matter.

Values arrive either as JSON-stored primitives (a ``Decimal`` as a string, a
date as ISO text) or as the native Python objects a service already parsed —
both shapes are accepted, since which one shows up depends on how the payload
reached us rather than on anything about the field.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sm_records._text import has_nul
from sm_records.constants import NUMBER_SCALE
from sm_records.schema.types import IndexKind

_QUANTUM = Decimal(1).scaleb(-NUMBER_SCALE)
"""``Numeric(19, 5)`` is the column, so five places is the contract. The
validator refuses a payload with more; the index quantises anyway so a value
written before that rule, or by a custom provider, cannot round-trip to a
number the column would have stored differently."""

_TRUE = frozenset({"true", "yes", "1", "on"})
_FALSE = frozenset({"false", "no", "0", "off"})


def coerce_text(value: object) -> str | None:
    """Anything with a string form is text. ``None`` is absence, not ``"None"``;
    an empty string is a present, empty value and does index.

    **A string carrying a NUL has no text form this column can hold.** Postgres
    refuses ``\x00`` in ``text`` outright, from the driver, while binding the
    parameter — so a value that reached here with one would be a 500 on the
    write that indexed it and a 500 on any filter that compared against it,
    the second of those reachable with no session at all. The validator
    refuses such a value on the way in (:mod:`sm_records._text`); this is the
    same rule stated where the value actually meets the column, for the two
    callers that do not come through the validator — a custom index provider
    (§7.6) and a reindex of a row written before the rule existed. ``None`` and
    not an exception, because that is this module's whole contract: a value
    with no place in this table is simply absent from the index, and the query
    builder turns the same ``None`` into the grammar's own refusal.
    """
    if value is None or has_nul(value):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float | Decimal | date | datetime):
        return str(value)
    return None


def coerce_number(value: object) -> Decimal | None:
    """``bool`` is rejected deliberately: ``True`` is not the number 1 in a
    field someone declared as a number, and indexing it as one makes a
    ``price > 0`` filter match a typo."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal | int | float | str):
        try:
            return Decimal(str(value)).quantize(_QUANTUM)
        except (InvalidOperation, ValueError, ArithmeticError):
            return None
    return None


def coerce_bool(value: object) -> bool | None:
    """Strict: a real ``bool``, or the strings JSON round-trips produce. An
    integer ``1`` is not accepted — see ``coerce_number`` for the symmetry."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    return None


def coerce_date(value: object) -> date | None:
    """A ``datetime`` is truncated to its calendar date — the date table exists
    precisely so a filter on it never depends on a connection's timezone
    (design doc §7.3), and keeping the time would reintroduce that."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def coerce_datetime(value: object) -> datetime | None:
    """Naive input is refused rather than assumed to be UTC. The column is
    ``DateTime(timezone=True)``; guessing the offset here would make the same
    payload index differently depending on where it was written."""
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed is None or parsed.tzinfo is None:
        return None
    return parsed


def coerce_ref(value: object) -> str | tuple[str, str] | None:
    """A relation value is ``{"type": ..., "uuid": ...}`` in the payload and a
    bare uuid in a filter. Returns the pair when the type travels with it, the
    uuid alone when it does not."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        uuid = value.get("uuid")
        target = value.get("type")
        if not isinstance(uuid, str) or not uuid:
            return None
        return (target, uuid) if isinstance(target, str) and target else uuid
    return None


COERCE: dict[IndexKind, Callable[[object], object | None]] = {
    IndexKind.TEXT: coerce_text,
    IndexKind.NUMBER: coerce_number,
    IndexKind.BOOL: coerce_bool,
    IndexKind.DATE: coerce_date,
    IndexKind.DATETIME: coerce_datetime,
}
"""The coercer per scalar index kind — one table, read by the writer
(``providers._entry``) and the query builder (``_predicates._coerce``), so the
two cannot pick different functions for the same kind. ``REF`` is absent: both
sides handle a relation through :func:`coerce_ref` on a path of its own."""
