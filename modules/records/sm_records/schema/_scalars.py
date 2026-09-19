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

from sm_records.constants import NUMBER_PRECISION, NUMBER_SCALE

MAX_INT_DIGITS = NUMBER_PRECISION - NUMBER_SCALE
"""Digits left of the point that ``Numeric(19, 5)`` can hold."""


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
    if value is None:
        return value
    if isinstance(value, bool):
        raise ValueError("expected an integer, got a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float | Decimal):
        if value != int(value):
            raise ValueError("must be a whole number")
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise ValueError("not an integer") from None
    raise ValueError("expected an integer")


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
