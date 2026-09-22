"""Scalar coercion for the payload validator: JSON in, a Python value out.

Split from ``_builders.py`` for the 300-line cap, and the seam is a real one:
everything here answers "what Python value does this JSON scalar mean, and is
it representable?", with no knowledge of field definitions, constraints or
pydantic. ``_builders`` composes these into an annotation per field type.

Every function is ``None``-tolerant — an optional field's base is a
``T | None`` union and the validators run on both arms — and every refusal
carries a message written for the person editing a record.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sm_records._text import check_no_nul, has_nul
from sm_records.constants import NUMBER_PRECISION, NUMBER_SCALE

MAX_INT_DIGITS = NUMBER_PRECISION - NUMBER_SCALE
"""Digits left of the point that ``Numeric(19, 5)`` can hold."""


def to_text(value: Any) -> Any:
    """The identity, minus the one character a text column cannot hold.

    Every text-like field type routes through here (:mod:`_builders`), so the
    NUL rule is one refusal with one wording rather than seven copies — and it
    is a *coercion* step rather than a constraint check because it must run
    before anything downstream sees the string, including the length and
    pattern checks whose messages would otherwise be the first thing a caller
    heard about a value that was never storable.
    """
    return check_no_nul(value)


def to_decimal(value: Any) -> Any:
    """Accept int/float/str/Decimal; refuse bool, which is an int in Python."""
    if value is None or isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("expected a number, got a boolean")
    if isinstance(value, int):
        return Decimal(value)
    # str() first: Decimal(0.1) inherits the binary float's noise and would
    # then fail the scale check below for a value the caller wrote as "0.1".
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            raise ValueError("not a number") from None
    raise ValueError("expected a number")


def check_decimal(value: Decimal | None) -> Decimal | None:
    """Enforce the ``Numeric(19, 5)`` contract of design §7.3. Refusing rather
    than rounding is the point: payload and index row must agree, and an index
    that silently rounds is a filter that silently returns the wrong rows."""
    if value is None:
        return None
    if not value.is_finite():
        raise ValueError("not a finite number")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > NUMBER_SCALE:
        raise ValueError(f"at most {NUMBER_SCALE} decimal places are stored")
    if len(str(abs(int(value)))) > MAX_INT_DIGITS:
        raise ValueError(f"at most {MAX_INT_DIGITS} digits before the decimal point")
    return value


def to_int(value: Any) -> Any:
    """Coerce to ``int``, under the same digit bound :func:`check_decimal`
    applies.

    Not a second, looser rule: an ``integer`` field indexes into the *same*
    ``Numeric(19, 5)`` column a ``number`` field does (``models/_index.py``),
    so a value past :data:`MAX_INT_DIGITS` is ``numeric field overflow`` from
    the driver on the statement that writes the index row — a 500, for a value
    the ``number`` type already answers with a clean 422 naming the digits.
    Python has no integer ceiling of its own, which is exactly why this has to
    be stated: ``10**13`` stored and filtered correctly, ``10**14`` did not.
    """
    if value is None:
        return value
    if isinstance(value, bool):
        raise ValueError("expected an integer, got a boolean")
    if isinstance(value, int):
        return _bounded_int(value)
    if isinstance(value, float | Decimal):
        if value != int(value):
            raise ValueError("must be a whole number")
        return _bounded_int(int(value))
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            raise ValueError("not an integer") from None
        return _bounded_int(parsed)
    raise ValueError("expected an integer")


def _bounded_int(value: int) -> int:
    if len(str(abs(value))) > MAX_INT_DIGITS:
        raise ValueError(f"at most {MAX_INT_DIGITS} digits")
    return value


def to_bool(value: Any) -> Any:
    """Narrow on purpose: ``"yes"`` is refused, so a form that sends it is a bug
    caught at the boundary instead of a column of silent ``False``."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError("expected true or false")


def to_date(value: Any) -> Any:
    """A calendar date, never a datetime — §7.3 on why they index separately."""
    if value is None:
        return value
    if isinstance(value, _datetime):
        raise ValueError("expected a calendar date, not a datetime")
    if isinstance(value, _date):
        return value
    if isinstance(value, str):
        try:
            return _date.fromisoformat(value.strip())
        except ValueError:
            raise ValueError("not an ISO date (YYYY-MM-DD)") from None
    raise ValueError("expected a date")


def to_datetime(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, _datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = _datetime.fromisoformat(value.strip())
        except ValueError:
            raise ValueError("not an ISO 8601 datetime") from None
    else:
        raise ValueError("expected a datetime")
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("must carry a timezone offset; a naive datetime is never guessed")
    return parsed


MAX_JSON_DEPTH = 32
"""How deeply a ``json`` field's value may nest.

Not a setting, because there is no install this is a policy decision for: a
hand-written configuration blob, a rich-text document tree and a nested
address book all live inside a dozen levels, and past thirty-two the value has
stopped being content and started being a shape. What it stops is a *write
that poisons every later read*: pydantic's Rust serializer gives up at roughly
250 levels with ``Circular reference detected (depth exceeded)``, which is a
500 — and on the import path the row is written and committed before any read
of the type runs into it, so one accepted payload turned every listing of that
type, the anonymous one included, into a permanent 500.

Refused here rather than caught there, because "this value cannot be
serialised" is a fact about the payload and belongs where every other one is:
in the validator, as the module's own 422, naming the field.
"""

MAX_JSON_NODES = 10_000
"""How many values (scalars, objects and arrays, counted together) one
``json`` field's value may hold.

Depth alone is not the whole shape: a flat array of a million numbers nests
one level and is still a payload nothing downstream should be asked to walk.
``max_payload_bytes`` bounds it eventually, but only *after* the value has
been validated and serialised — this is the cheap bound, taken during the
walk the depth check is already making."""


NUL_IN_JSON = "holds a string with a NUL character (\\x00)"
"""The NUL wording for a *nested* value. ``_text.NUL_PROBLEM`` says "must not
contain"; inside a document the offending string may be anywhere, so the
message says what was found rather than what the field may not be."""


def check_json_shape(value: Any) -> Any:
    """Refuse a ``json`` value that nests too deeply or holds too many nodes.

    Iterative, with an explicit stack, and not recursive: a recursive walk of a
    value deep enough to be refused is itself a ``RecursionError`` — the 500
    this function exists to replace, arriving from one frame further out.

    The traversal is the same one for all three rules, so a value is walked
    once. Counting every node (not only the containers) is what makes the node
    bound meaningful for the flat-and-huge shape the depth bound cannot see,
    and the same visit is where a nested NUL is caught: a ``json`` value is
    stored in a ``jsonb`` column, which refuses ``\u0000`` exactly as ``text``
    does, so a NUL three objects down is the same 500 a top-level one is.
    Object *keys* are walked too — they are strings the column has to store.
    """
    if value is None:
        return value
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise ValueError(f"holds more than {MAX_JSON_NODES} values")
        if has_nul(node):
            raise ValueError(NUL_IN_JSON)
        if isinstance(node, dict | list):
            if depth > MAX_JSON_DEPTH:
                raise ValueError(f"is nested more than {MAX_JSON_DEPTH} levels deep")
            if isinstance(node, dict):
                if any(has_nul(key) for key in node):
                    raise ValueError(NUL_IN_JSON)
                children: Any = node.values()
            else:
                children = node
            stack.extend((child, depth + 1) for child in children)
    return value
