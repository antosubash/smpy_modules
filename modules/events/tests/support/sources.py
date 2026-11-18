"""Fake plugin sources and a way to install them: the runner's and the API's test doubles.

:func:`install` puts them in a fresh registry through the real loader (the built-ins
first), as a plugin's ``register`` would, so the registry the code under test reads is
the production one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict
from sm_events.calendar import extensions, registry
from sm_events.calendar.extension_types import SourceOccurrence, SourceSettingsError


def namespace(ident: str) -> str:
    return ident.split(":", 1)[0]


def install(monkeypatch, *sources: Any, types: tuple[Any, ...] = ()) -> None:
    """A registry holding the built-ins plus ``sources`` and ``types``, frozen on first
    read. Call ``registry.reset_registry()`` (the ``fresh_registry`` fixture does)."""
    registry.reset_registry()
    real = list(extensions._BUILTIN_LOADERS)

    def plugins() -> None:
        for source in sources:
            registry.add_source(source, namespace=namespace(source.id))
        for etype in types:
            registry.add_type(etype, namespace=namespace(etype.id))

    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", [*real, plugins])
    monkeypatch.setattr(extensions, "_plugins", list)


def item(key: str = "a", title: str = "Item", **fields: Any) -> SourceOccurrence:
    """A timed item on 2026-07-02 unless ``fields`` say otherwise."""
    from datetime import UTC, datetime

    fields.setdefault("start", datetime(2026, 7, 2, 10, tzinfo=UTC))
    fields.setdefault("end", datetime(2026, 7, 2, 11, tzinfo=UTC))
    return SourceOccurrence(key=key, title=title, **fields)


class DeskSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = "a"
    count: int = 1


class FakeSource:
    """A source whose behaviour is a coroutine function over ``(ctx, start, end)``."""

    label_key = "acme.fake"
    public = False
    color = None
    icon = None
    settings_model: type[BaseModel] | None = None

    def __init__(
        self,
        ident: str = "acme:fake",
        behave: Callable[..., Any] | None = None,
        *,
        public: bool = False,
        settings_model: type[BaseModel] | None = None,
    ) -> None:
        self.id = ident
        self.public = public
        self.settings_model = settings_model
        self.calls: list[Any] = []
        self._behave = behave

    async def occurrences(self, ctx, start, end):
        self.calls.append((ctx, start, end))
        if self._behave is None:
            return []
        return await self._behave(ctx, start, end)


class SettingsSource(FakeSource):
    """Has a settings model and a ``check_settings`` that refuses ``field == "bad"``,
    sleeps for ``field == "slow"`` and raises for ``field == "boom"``."""

    def __init__(self, ident: str = "acme:desk") -> None:
        super().__init__(ident, settings_model=DeskSettings)
        self.checked: list[Any] = []

    async def check_settings(self, sctx, settings):
        self.checked.append((sctx, settings))
        if settings.field == "bad":
            raise SourceSettingsError(("field",), "That field is not allowed")
        if settings.field == "slow":
            await asyncio.sleep(10)
        if settings.field == "boom":
            raise RuntimeError("secret value leaked in a message")
        if settings.field == "sql":
            from sqlalchemy import text

            await sctx.db.execute(text("SELECT * FROM nope_not_a_table"))
