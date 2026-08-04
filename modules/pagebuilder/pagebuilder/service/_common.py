"""Sentinels and helpers shared by the service mixins.

Lives in its own module so ``_workflow`` can import it without reaching back
into ``pagebuilder.service``, which imports ``_workflow`` in turn.
"""

from __future__ import annotations

from datetime import UTC, datetime


class _Unset:
    """Sentinel separating ``field=None`` (clear) from "field not provided"."""


_UNSET = _Unset()


def _normalize_to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
