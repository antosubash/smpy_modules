"""Call plugin sources for one read: isolated, bounded and reported on.

Each ``(calendar, source)`` pair is one call, run **sequentially** (they share the
request's session) through :func:`~sm_events.calendar.plugins.plugin_isolation.run_isolated`: a
savepoint that is rolled back, a wall-clock timeout, and a check that the plugin did not
write. All calls of one read share a phase budget, at most ``SOURCE_CALLS_MAX`` pairs are
called, and one answer is at most ``SOURCE_CALL_MAX_ITEMS`` items. What comes back is
validated (:mod:`~sm_events.calendar.plugins.plugin_validate`) or the whole answer is refused.

A failing, slow or misbehaving plugin degrades to a :class:`SourceStatus` the UI can
show; it never raises, hangs or poisons the transaction. Exceptions are logged with the
source id and the exception class only: what a plugin says may hold its settings.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from sm_events.calendar.occurrence import Occurrence
from sm_events.calendar.plugins import source_entries
from sm_events.calendar.plugins.extension_types import (
    Source,
    SourceCalendar,
    SourceContext,
    SourceError,
    SourceStatus,
    SourceViewer,
)
from sm_events.calendar.plugins.plugin_isolation import PluginWrote, SessionBroken, run_isolated
from sm_events.calendar.plugins.plugin_validate import InvalidPluginItem, to_occurrences
from sm_events.calendar.sources import sort_key
from sm_events.core import constants

__all__ = ["Call", "RunResult", "run_sources"]

logger = logging.getLogger(__name__)

OK, TRUNCATED, FAILED, TIMEOUT = "ok", "truncated", "failed", "timeout"
SKIPPED, NOT_INSTALLED = "skipped", "not_installed"
CODE_RAISED, CODE_WROTE, CODE_SESSION = "raised", "wrote", "session"
CODE_BUDGET, CODE_TOO_MANY_CALLS = "budget", "too_many_calls"
CODE_INVALID_SETTINGS, CODE_INVALID_ANSWER = "invalid_settings", "invalid_answer"
CODE_TOO_MANY_ITEMS = "too_many_items"


@dataclass(frozen=True)
class Call:
    calendar: SourceCalendar
    entry: source_entries.SourceEntry
    source: Source | None
    """``None``: the entry names a source this host does not have (reported, not called)."""


@dataclass(frozen=True)
class RunResult:
    items: list[Occurrence]
    statuses: list[SourceStatus]
    truncated: bool


class _Phase:
    """The read's shared time budget and call count."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock, self.began, self.called, self.broken = clock, clock(), 0, False

    def slice(self) -> float:
        return min(
            constants.SOURCE_TIMEOUT_SECONDS,
            constants.SOURCE_PHASE_SECONDS - (self.clock() - self.began),
        )


def _status(call: Call, status: str, code: str | None = None) -> SourceStatus:
    return SourceStatus(id=call.entry.id, calendar_id=call.calendar.id, status=status, code=code)  # type: ignore[arg-type]


def _blocked(call: Call, phase: _Phase) -> SourceStatus | None:
    """Why this call is not made, if it is not."""
    if call.source is None:
        return _status(call, NOT_INSTALLED)
    if phase.broken:
        return _status(call, SKIPPED, CODE_SESSION)
    if phase.called >= constants.SOURCE_CALLS_MAX:
        return _status(call, SKIPPED, CODE_TOO_MANY_CALLS)
    if phase.slice() < constants.SOURCE_MIN_SLICE_SECONDS:
        return _status(call, SKIPPED, CODE_BUDGET)
    return None


def _log(call: Call, what: str) -> None:
    logger.error("events: source %s on calendar %s: %s", call.entry.id, call.calendar.id, what)


async def _one(
    db: Any,
    call: Call,
    phase: _Phase,
    base: dict[str, Any],
    window: tuple[datetime, datetime],
) -> tuple[list[Occurrence], SourceStatus]:
    source = call.source
    assert source is not None
    try:
        settings = source_entries.settings_of(source, call.entry)
    except ValidationError:
        return [], _status(call, FAILED, CODE_INVALID_SETTINGS)
    ctx = SourceContext(
        calendar=call.calendar,
        settings=settings,
        limit=constants.SOURCE_CALL_MAX_ITEMS,
        db=db,
        **base,
    )
    phase.called += 1
    try:
        answer = await run_isolated(
            db, phase.slice(), lambda session: source.occurrences(replace(ctx, db=session), *window)
        )
        if not isinstance(answer, list | tuple):
            return [], _status(call, FAILED, CODE_INVALID_ANSWER)
        if len(answer) > constants.SOURCE_CALL_HARD_MAX_ITEMS:
            return [], _status(call, FAILED, CODE_TOO_MANY_ITEMS)
        items = to_occurrences(
            answer,
            source_id=source.id,
            calendar=call.calendar,
            start=window[0],
            end=window[1],
            default_lang=base["default_locale"],
        )
    except TimeoutError:
        return [], _status(call, TIMEOUT)
    except PluginWrote:
        _log(call, "wrote to the session")
        return [], _status(call, FAILED, CODE_WROTE)
    except SessionBroken as exc:
        phase.broken = True
        _log(call, f"the session could not be restored ({exc})")
        return [], _status(call, FAILED, CODE_SESSION)
    except SourceError as exc:
        return [], _status(call, FAILED, exc.code)
    except InvalidPluginItem as exc:
        return [], _status(call, FAILED, exc.code)
    except Exception as exc:
        _log(call, f"raised {type(exc).__name__}")
        return [], _status(call, FAILED, CODE_RAISED)
    if len(items) > constants.SOURCE_CALL_MAX_ITEMS:
        items = sorted(items, key=sort_key)[: constants.SOURCE_CALL_MAX_ITEMS]
        return items, _status(call, TRUNCATED)
    return items, _status(call, OK)


async def run_sources(
    db: Any,
    calls: Sequence[Call],
    *,
    tenant_id: str,
    viewer: SourceViewer | None,
    start: datetime,
    end: datetime,
    locale: str,
    default_locale: str,
    clock: Callable[[], float] = time.monotonic,
) -> RunResult:
    """Every call in order; items sorted by :func:`sort_key` and deduplicated on
    ``(source, calendar_id, key)`` (the first kept). Never raises for a plugin's doing."""
    phase = _Phase(clock)
    base = {
        "tenant_id": tenant_id,
        "viewer": viewer,
        "locale": locale,
        "default_locale": default_locale,
    }
    items: list[Occurrence] = []
    statuses: list[SourceStatus] = []
    for call in calls:
        if (skipped := _blocked(call, phase)) is not None:
            statuses.append(skipped)
            continue
        found, status = await _one(db, call, phase, base, (start, end))
        items.extend(found)
        statuses.append(status)
    seen: set[tuple[str, Any, str]] = set()
    unique: list[Occurrence] = []
    for occ in sorted(items, key=sort_key):
        ident = (occ.source, occ.calendar_id, occ.key)
        if ident not in seen:
            seen.add(ident)
            unique.append(occ)
    return RunResult(unique, statuses, any(s.status == TRUNCATED for s in statuses))
