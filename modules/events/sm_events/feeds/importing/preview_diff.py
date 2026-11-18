"""Would applying an item change anything? Asked with the write's own comparison.

The preview must call an item *unchanged* exactly when the apply step will, so this does not
compare fields a second time: it runs the very write (:func:`~sm_events.content._core.apply_patch`
with the import's patch and its override replacement) in a savepoint that is **always rolled
back**, and reports whether it raised :class:`~sm_events.content.guard.Unchanged`. Nothing it does
survives, and the bus is muted for it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from sm_events.content._core import apply_patch
from sm_events.content.guard import Unchanged
from sm_events.feeds.importing.model import MappedEvent
from sm_events.feeds.importing.write import _muted, _patch, _replace_overrides
from sm_events.models import Event, EventImportItem

__all__ = ["is_unchanged"]


async def is_unchanged(db: Any, actor: str, row: EventImportItem, locales: tuple[str, ...]) -> bool:
    """``True`` when the write of ``row`` (an ``update`` item) would change nothing. The
    rollback expires the session's objects: the caller reads what it needs first and refreshes
    after. Any doubt (the event is gone, the write raises something else) is ``False``: the apply
    step decides."""
    mapped = MappedEvent.model_validate(row.payload)
    event = (
        await db.execute(
            select(Event).where(Event.id == row.existing_event_id)  # type: ignore[arg-type]
        )
    ).scalar_one_or_none()
    if event is None:
        return False
    same = False
    async with _muted(db):
        probe = await db.begin_nested()
        try:
            patch = await _patch(db, None, row, mapped, event, locales)
            await apply_patch(
                db,
                actor,
                event,
                patch,
                locales,
                after=lambda ev: _replace_overrides(db, ev, mapped.overrides),
            )
        except Unchanged:
            same = True
        except Exception:
            same = False
        finally:
            await probe.rollback()
    return same
