"""Helpers for the event-write tests: bodies, principals and a bus that records."""

from __future__ import annotations

from typing import Any

from simple_module_core.events import Event, EventBus
from sm_events.content import bus
from sm_events.content.events_write import create_event
from sm_events.contracts import events as contract
from sm_events.contracts.extensions import SourceViewer
from sm_events.models import Calendar, Revision
from sm_events.models import Event as EventRow
from sm_events.web.schemas.events_in import EventCreate
from sqlalchemy import func, select

from tests.support.access import principal

LOCALES = ("en", "de")
V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
OWNER_P = principal("o", V, E, P)  # owner with publish
OWNER = principal("o", V, E)  # owner without publish
SE = principal("se", V)  # edit share
SV = principal("sv", V)  # view share
VIEWER = principal("v", V)
MANAGER = principal("m", V, M)
MANAGER_P = principal("m", V, M, P)
STRANGER = principal("z")


def times(start="2026-07-01T10:00", end="2026-07-01T11:00", **kw) -> dict[str, Any]:
    return {"timezone": "Europe/Vienna", "start": start, "end": end, **kw}


def create_body(cal: Calendar, **kw: Any) -> EventCreate:
    body: dict[str, Any] = {
        "calendar_id": cal.id,
        "times": times(),
        "texts": {"en": {"title": "Concert"}},
    }
    body.update(kw)
    return EventCreate(**body)


EDITOR = SourceViewer(
    user_id="o", roles=(), permissions=frozenset({V, E, P, M}), role_map=None
)  # the writer's caller, for registration settings


async def make(db, who, cal, **kw) -> EventRow:
    viewer = kw.pop("viewer", EDITOR)
    return await create_event(db, who, create_body(cal, **kw), locales=LOCALES, viewer=viewer)


class Recorder:
    """A bus every bus event of the four kinds lands on, in order."""

    def __init__(self) -> None:
        self.bus = EventBus()
        self.seen: list[Event] = []
        for cls in (
            contract.EventPublished,
            contract.EventRescheduled,
            contract.EventCancelled,
            contract.EventDeleted,
        ):
            self.bus.subscribe(cls, self._on)

    async def _on(self, event: Event) -> None:
        self.seen.append(event)


def recording(db) -> Recorder:
    rec = Recorder()
    bus.attach(db, rec.bus)
    return rec


async def revision_count(db, event_id) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Revision).where(Revision.event_id == event_id)
        )
    ).scalar_one()
