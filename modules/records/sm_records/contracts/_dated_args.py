"""Argument checks for the dated-records contract (kept apart to stay under the size cap)."""

from __future__ import annotations

from typing import Final

from simple_module_db import is_valid_tenant_id

from sm_records.core import locales
from sm_records.core.settings import RecordsSettings

MAX_DATED_BATCH: Final = 1000


def _tenant(tenant_id: object) -> str:
    if not isinstance(tenant_id, str) or not is_valid_tenant_id(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    return tenant_id


def _public_locale(locale: str | None, settings: RecordsSettings | None) -> None:
    """The public is asked for one language that the site publishes, never defaulted: records'
    own public read requires it too, and refuses one it does not publish."""
    if locale is None:
        raise ValueError("a public read needs a locale")
    if locale not in locales.supported(settings or _ambient_settings()):
        raise ValueError(f"{locale!r} is not a content locale")


def _ambient_settings() -> RecordsSettings:
    """Records' settings as a worker or a web process without an ``app`` reads them; where that
    is not available the defaults (one language), which can only narrow what the public sees."""
    from sm_records.contracts._newsletter_settings import records_settings

    try:
        return records_settings(None)
    except Exception:
        return RecordsSettings()


def _limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_DATED_BATCH:
        raise ValueError(f"limit must be an int from 1 to {MAX_DATED_BATCH}")
    return limit
