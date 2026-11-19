"""An import announces nothing: no in-process event and no outbox row, for a create, an update
and an override alike (5,000 imported events must not become 5,000 notifications)."""

from __future__ import annotations

from datetime import UTC, datetime

from simple_module_core.events import EventBus
from sm_events.content import bus as bus_module
from sm_events.contracts import events as contract
from sm_events.core.clock import utcnow
from sm_events.feeds.importing.write import write_item
from sm_events.models import Event
from sqlalchemy import select

from tests.content.test_bus import Transport
from tests.feeds.importing.staging_support import seed
from tests.feeds.importing.write_support import make_item, mapped_event, moved, setup

LOCALES = ("en", "de")
PUBLISHER = ("events.view", "events.manage", "events.publish")
TIMES = {"timezone": "Europe/Vienna", "start": "2026-07-06T10:00", "end": "2026-07-06T11:00"}


def _bus(seen: list[object], transport: Transport) -> EventBus:
    ev_bus = EventBus()
    ev_bus.durable_transport = transport  # type: ignore[assignment]

    async def record(event):
        seen.append(event)

    async def handle(event, ctx):
        return None

    for name in contract.__all__:
        cls = getattr(contract, name)
        ev_bus.subscribe(cls, record)
        ev_bus.subscribe_durable(cls, handle, name=f"test.{name}")
    return ev_bus


async def test_an_import_is_silent_in_process_and_in_the_outbox(db):
    seen: list[object] = []
    transport = Transport()
    ev_bus = _bus(seen, transport)
    bus_module.attach(db, ev_bus)
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)

    async def write(item):
        return await write_item(db, imp, item, locales=LOCALES, now=utcnow())

    first = datetime(2026, 7, 6, 8, tzinfo=UTC)
    created = await write(
        await make_item(
            db,
            imp,
            mapped_event(
                times=TIMES,
                rrule="FREQ=WEEKLY;COUNT=4",
                overrides=[{"original_start": first, "kind": "skipped"}],
            ),
        )
    )
    assert created.outcome == "created"
    event = (await db.execute(select(Event))).scalar_one()
    second = datetime(2026, 7, 13, 8, tzinfo=UTC)
    updated = await write(
        await make_item(
            db,
            imp,
            mapped_event(
                title="Renamed",
                cancelled=True,
                times={**TIMES, "start": "2026-07-06T14:00", "end": "2026-07-06T15:00"},
                rrule="FREQ=WEEKLY;COUNT=4",
                overrides=[moved(second, "2026-07-13T15:00", "2026-07-13T16:00")],
            ),
            seq=2,
            verdict="update",
            existing=event.id,
            revision=event.revision,
        )
    )
    assert updated.outcome == "updated"
    await bus_module.commit(db)
    assert seen == [] and transport.calls == []
    assert db.info.get(bus_module.BUS_KEY) is ev_bus  # the session has its bus back
    assert not db.info.get(bus_module.DURABLE_KEY)
