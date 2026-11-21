"""What a reader sees of a calendar's source settings: only a manager sees any, and then only
as far as each source's own ``view_settings`` says (see :class:`~sm_events.calendar.plugins.
extension_types.Source`). Kept apart from :mod:`sm_events.calendar.plugins.source_entries`
(storage and writes) to stay under the size cap."""

from __future__ import annotations

import copy
import logging
from dataclasses import replace
from typing import Any

from sm_events.calendar.plugins import registry
from sm_events.calendar.plugins.extension_types import (
    SettingsContext,
    SettingsProblem,
    SettingsView,
    Source,
    SourceViewer,
)
from sm_events.calendar.plugins.plugin_isolation import run_isolated
from sm_events.calendar.plugins.source_entries import SourceEntry, read, shown, source_calendar
from sm_events.core import constants
from sm_events.models import Calendar

__all__ = ["shown_for"]

logger = logging.getLogger(__name__)


async def shown_for(
    db: Any,
    tenant_id: str,
    viewer: SourceViewer | None,
    calendar: Calendar,
    *,
    with_settings: bool,
) -> list[dict[str, Any]]:
    """:func:`shown` for a reader: with settings only for those who can manage the calendar, and
    each source's own ``view_settings`` deciding how much of its settings that reader may see
    (and which problems they may be told about). A source that fails to answer shows ``{}``."""
    base = shown(calendar.sources, with_settings=False)
    if not with_settings or viewer is None:
        return base
    context = SettingsContext(
        tenant_id=tenant_id, viewer=viewer, calendar=source_calendar(calendar), db=db
    )
    for entry, out in zip(read(calendar.sources), base, strict=True):
        source = registry.get_source(entry.id)
        if source is None:
            continue  # nothing can redact it: its settings are not shown at all
        out["settings"], out["problems"] = await _view(source, db, entry, context)
    return base


async def _view(
    source: Source, db: Any, entry: SourceEntry, ctx: SettingsContext
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    view = getattr(source, "view_settings", None)
    if view is None:
        return entry.settings, []
    try:
        got = await run_isolated(
            db,
            constants.SOURCE_TIMEOUT_SECONDS,
            lambda session: view(replace(ctx, db=session), copy.deepcopy(entry.settings)),
        )
    except Exception as exc:
        logger.error("events: view_settings of %s failed (%s)", source.id, type(exc).__name__)
        return {}, []  # fail closed: nothing the plugin could not vouch for is shown
    if not isinstance(got, SettingsView) or not isinstance(got.settings, dict):
        return {}, []
    problems = [
        {"loc": list(p.loc), "code": p.code, "message": p.message}
        for p in got.problems
        if isinstance(p, SettingsProblem)
    ]
    return got.settings, problems
