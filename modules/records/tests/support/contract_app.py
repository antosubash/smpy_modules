"""The ``app`` records' newsletter contracts fetch their settings from (#336)."""

from __future__ import annotations

from types import SimpleNamespace

from sm_records.core.settings import RecordsSettings


def contract_app(settings: RecordsSettings | None = None) -> SimpleNamespace:
    """An app whose ``state.sm_records.settings`` is ``settings`` (the defaults by default)."""
    services = SimpleNamespace(settings=settings or RecordsSettings())
    return SimpleNamespace(state=SimpleNamespace(sm_records=services))
