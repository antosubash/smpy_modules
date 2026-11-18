"""A calendar's enabled sources: what is stored, how it is read back and how it is written.

``events_calendar.sources`` is a JSON list of ``{"id", "settings"}`` objects, at most
``CALENDAR_SOURCES_MAX``. The built-in ``events`` source is always on and never listed.
The reader is tolerant (an older plain-string entry is an entry with no settings, and
anything malformed is dropped and logged); writes always store objects. Settings are
validated against the plugin's declared model, then by its optional ``check_settings``
(on a connection of its own, with a timeout), and stored as that model's JSON dump.

Settings are stored in the clear and shown only to those who can manage the calendar:
a plugin that needs a secret keeps it in its own module settings (sealed there) and
names it from here.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from sm_events.calendar.plugins import registry
from sm_events.calendar.plugins.extension_types import (
    SettingsContext,
    Source,
    SourceCalendar,
    SourceSettingsError,
    SourceViewer,
)
from sm_events.calendar.plugins.plugin_isolation import run_isolated
from sm_events.core import constants
from sm_events.core.errors import Stale
from sm_events.core.errors_extensions import (
    BuiltinSource,
    DuplicateSource,
    SourceUnavailable,
    TooManySources,
    UnknownSource,
)
from sm_events.models import Calendar

__all__ = [
    "SourceEntry",
    "dump",
    "read",
    "settings_of",
    "shown",
    "source_calendar",
    "version",
    "write_entries",
]

logger = logging.getLogger(__name__)

_BODY = ("body", "sources")


@dataclass(frozen=True)
class SourceEntry:
    id: str
    settings: dict[str, Any]


def read(raw: Any) -> list[SourceEntry]:
    """The entries stored in a calendar's ``sources`` column; malformed ones are dropped."""
    if not isinstance(raw, list):
        if raw is not None:
            logger.warning("events: a calendar's sources are not a list; ignored")
        return []
    found: list[SourceEntry] = []
    seen: set[str] = set()
    dropped = 0
    for item in raw:
        if isinstance(item, str):
            item = {"id": item, "settings": {}}
        ident = item.get("id") if isinstance(item, dict) else None
        settings = item.get("settings", {}) if isinstance(item, dict) else None
        if not isinstance(ident, str) or not isinstance(settings, dict) or ident in seen:
            dropped += 1
            continue
        seen.add(ident)
        found.append(SourceEntry(ident, settings))
    if dropped:
        logger.warning("events: dropped %d malformed or repeated source entries", dropped)
    return found[: constants.CALENDAR_SOURCES_MAX]


def dump(entries: Sequence[SourceEntry]) -> list[dict[str, Any]]:
    return [{"id": e.id, "settings": e.settings} for e in entries]


def settings_of(source: Source, entry: SourceEntry) -> BaseModel | None:
    """The entry's settings as the source's model; ``ValidationError`` when they no longer
    fit it. ``None`` for a source that declares no model."""
    model = source.settings_model
    return None if model is None else model.model_validate(entry.settings)


def source_calendar(calendar: Calendar) -> SourceCalendar:
    return SourceCalendar(
        id=calendar.id,
        slug=calendar.slug,
        name=calendar.name,
        visibility=calendar.visibility,
        default_timezone=calendar.default_timezone,
        color=calendar.color,
    )


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), default=str))


def _error(loc: tuple[Any, ...], msg: str, kind: str = "value_error") -> dict[str, Any]:
    return {"loc": loc, "msg": msg, "type": kind}


def _validated(source: Source, index: int, settings: dict[str, Any]) -> tuple[SourceEntry, Any]:
    """The stored form of ``settings`` for ``source``, and the model instance."""
    where = (*_BODY, index, "settings")
    if _size(settings) > constants.SOURCE_SETTINGS_MAX_BYTES:
        raise RequestValidationError([_error(where, "The settings are too large")])
    if source.settings_model is None:
        if settings:
            raise RequestValidationError([_error(where, "This source has no settings")])
        return SourceEntry(source.id, {}), None
    try:
        model = source.settings_model.model_validate(settings)
    except ValidationError as exc:
        # ``input`` is left out on purpose: a settings value is never echoed back.
        raise RequestValidationError(
            [_error((*where, *e["loc"]), e["msg"], e["type"]) for e in exc.errors()]
        ) from None
    return SourceEntry(source.id, model.model_dump(mode="json")), model


async def _check(
    source: Source,
    db: Any,
    index: int,
    model: Any,
    ctx: SettingsContext,
) -> None:
    check = getattr(source, "check_settings", None)
    if check is None:
        return
    try:
        await run_isolated(
            db,
            constants.SOURCE_TIMEOUT_SECONDS,
            lambda session: check(replace(ctx, db=session), model),
        )
    except SourceSettingsError as exc:
        loc = (*_BODY, index, "settings", *exc.loc)
        raise RequestValidationError([_error(loc, exc.message)]) from None
    except Exception as exc:
        # Class and source id only: what the plugin said may hold a setting's value.
        logger.error("events: check_settings of %s failed (%s)", source.id, type(exc).__name__)
        raise SourceUnavailable from None


async def write_entries(
    db: Any,
    tenant_id: str,
    viewer: SourceViewer,
    calendar: Calendar,
    incoming: Sequence[Any],
    expected: str,
) -> list[SourceEntry]:
    """Validate ``incoming`` (``CalendarSourceIn``: ``id`` and ``settings``) and store it
    on ``calendar``; the caller has already checked the right to change what the
    calendar's audience sees. ``expected`` is the ``sources_version`` the caller read: another
    write since is :class:`Stale`. Raises :class:`BuiltinSource`, :class:`DuplicateSource`,
    :class:`TooManySources`, :class:`UnknownSource`, a ``RequestValidationError`` for
    settings that do not fit, or :class:`SourceUnavailable`."""
    if expected != version(calendar.sources):
        raise Stale
    ids = [item.id for item in incoming]
    if constants.SOURCE_EVENTS in ids:
        raise BuiltinSource
    if len(set(ids)) != len(ids):
        raise DuplicateSource
    if len(ids) > constants.CALENDAR_SOURCES_MAX:
        raise TooManySources
    stored = {e.id: e for e in read(calendar.sources)}
    entries: list[SourceEntry] = []
    context = SettingsContext(
        tenant_id=tenant_id, viewer=viewer, calendar=source_calendar(calendar), db=db
    )
    for index, item in enumerate(incoming):
        source = registry.get_source(item.id)
        if source is None:
            # Not installed here: kept only if it is exactly what is stored.
            old = stored.get(item.id)
            if old is None or json.dumps(old.settings, sort_keys=True) != json.dumps(
                item.settings, sort_keys=True
            ):
                raise UnknownSource
            entries.append(old)
            continue
        entry, model = _validated(source, index, item.settings)
        await _check(source, db, index, model, context)
        entries.append(entry)
    calendar.sources = dump(entries)
    await db.flush()
    return entries


def version(raw: Any) -> str:
    """A token for the stored entries: the caller sends it back with a write, which is refused
    (``stale``) when somebody wrote since, so two managers never overwrite each other."""
    canonical = json.dumps(dump(read(raw)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def shown(raw: Any, *, with_settings: bool) -> list[dict[str, Any]]:
    """The entries as ``CalendarSourceOut`` fields. Settings go only to those who can manage
    the calendar (``with_settings``); everyone else who can see it gets ``{}``."""
    out: list[dict[str, Any]] = []
    for entry in read(raw):
        source = registry.get_source(entry.id)
        out.append(
            {
                "id": entry.id,
                "settings": entry.settings if with_settings else {},
                "installed": source is not None,
                "label_key": source.label_key if source is not None else None,
            }
        )
    return out
