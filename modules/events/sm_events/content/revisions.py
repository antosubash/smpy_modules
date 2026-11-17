"""An event's history: one row per write, with a JSON-safe snapshot.

The snapshot holds every ``Event`` column except the id, the tenant and the audit
and soft-delete columns, plus ``texts`` (``{locale: every text field}``) and
``overrides``. ``Revision.number`` is the event's revision after the write. Only
the newest ``REVISIONS_KEPT`` are kept. History is read-only: nothing restores a
revision.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import defer

from sm_events.content.texts import texts_of
from sm_events.core import constants
from sm_events.core.errors import NotFound
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Event, EventText, OccurrenceOverride, Revision

__all__ = ["get_revision", "list_revisions", "record", "snapshot"]

_EXCLUDED = frozenset(
    {"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by"}
    | {"is_deleted", "deleted_at", "deleted_by"}
)
EVENT_COLUMNS = tuple(
    c.name
    for c in Event.__table__.columns
    if c.name not in _EXCLUDED  # type: ignore[attr-defined]
)
_TEXT_FIELDS = (
    "slug",
    "title",
    "summary",
    "description",
    "seo_title",
    "seo_description",
    "noindex",
)


def _safe(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def snapshot(
    event: Event, texts: Mapping[str, EventText], overrides: Sequence[OccurrenceOverride]
) -> dict[str, Any]:
    """The event as JSON-safe values."""
    out: dict[str, Any] = {name: _safe(getattr(event, name)) for name in EVENT_COLUMNS}
    out["texts"] = {
        locale: {f: getattr(row, f) for f in _TEXT_FIELDS} for locale, row in sorted(texts.items())
    }
    out["overrides"] = [
        {
            "original_start": _safe(o.original_start),
            "kind": o.kind,
            "starts_at": _safe(o.starts_at),
            "ends_at": _safe(o.ends_at),
            "note": o.note,
        }
        for o in sorted(overrides, key=lambda o: o.original_start)
    ]
    return out


async def record(
    db: Any, event: Event, *, action: str, actor: str | None, note: str | None = None
) -> Revision:
    """Write the history row for the event's current revision and prune the old."""
    texts = (await texts_of(db, [event.id]))[event.id]
    overrides = (
        (
            await db.execute(
                select(OccurrenceOverride).where(OccurrenceOverride.event_id == event.id)
            )
        )
        .scalars()
        .all()
    )
    row = Revision(
        event_id=event.id,
        number=event.revision,
        action=action,
        actor=actor,
        snapshot=snapshot(event, texts, overrides),
        note=note,
    )
    db.add(row)
    await db.flush()
    table = Revision.__table__  # type: ignore[attr-defined]
    await db.execute(
        delete(table).where(
            table.c.tenant_id == bound_tenant(),
            table.c.event_id == event.id,
            table.c.number <= event.revision - constants.REVISIONS_KEPT,
        )
    )
    return row


async def list_revisions(db: Any, event_id: uuid.UUID) -> list[Revision]:
    """Newest first, without the snapshots."""
    stmt = (
        select(Revision)
        .where(Revision.event_id == event_id)
        .options(defer(Revision.snapshot))  # type: ignore[arg-type]
        .order_by(Revision.number.desc())  # type: ignore[attr-defined]
        .limit(constants.REVISIONS_KEPT)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_revision(db: Any, event_id: uuid.UUID, number: int) -> Revision:
    row = (
        await db.execute(
            select(Revision).where(Revision.event_id == event_id, Revision.number == number)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound
    return row
