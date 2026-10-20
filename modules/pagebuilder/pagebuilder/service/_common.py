"""Sentinels and helpers shared by the service mixins.

Lives in its own module so ``_workflow`` can import it without reaching back
into ``pagebuilder.service``, which imports ``_workflow`` in turn.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pagebuilder.models import Page


class _Unset:
    """Sentinel separating ``field=None`` (clear) from "field not provided"."""


_UNSET = _Unset()


def _normalize_to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _elapsed(value: datetime | None, now: datetime) -> bool:
    """Whether a stored timestamp, once normalized to UTC, is due or past."""
    aware = _normalize_to_utc(value)
    return aware is not None and aware <= now


def _spend_schedule(page: Page, now: datetime) -> None:
    """Clear ``publish_at`` and an ``unpublish_at`` that has already elapsed."""
    page.publish_at = None
    if _elapsed(page.unpublish_at, now):
        page.unpublish_at = None
