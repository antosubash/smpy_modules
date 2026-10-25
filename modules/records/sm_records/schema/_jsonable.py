"""A validated payload as the JSON column stores it — split from
:mod:`sm_records.schema.compile` (which re-exports it) for the 300-line cap."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

__all__ = ["to_jsonable"]


def to_jsonable(data: Any) -> Any:
    """Convert a validated payload to types the JSON column can store.

    ``Decimal`` becomes a string, not a float: round-tripping through a float
    is exactly the precision loss the ``number`` contract (§7.3) exists to
    prevent, and it would put the payload and the index out of step.
    """
    if isinstance(data, Decimal):
        return str(data)
    if isinstance(data, date):  # ``datetime`` included: it is a ``date``
        return data.isoformat()
    if isinstance(data, dict):
        return {key: to_jsonable(value) for key, value in data.items()}
    if isinstance(data, list | tuple):
        return [to_jsonable(item) for item in data]
    return data
