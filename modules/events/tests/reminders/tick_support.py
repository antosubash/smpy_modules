"""What the tick tests share: a mailbox, seeding, one pass, the ledger."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from simple_module_db import no_tenant
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.models import ReminderSent
from sm_events.reminders import tick
from sm_events.reminders.runtime import web_runtime
from sqlalchemy import select

from tests.reminders.support import bulk_follows, published, world
from tests.support.calendars import seed_series

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)
TEN = datetime(2026, 7, 1, 10, tzinfo=UTC)
SETTINGS = EventsSettings(content_locales=("en", "de"))


class Mailbox:
    delivers_email = True

    def __init__(self, delay: float = 0.0):
        self.messages = []
        self.delay = delay

    async def send(self, message) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.messages.append(message)


async def seed(state, *, users=("v",), lead=60, tenant="default", visibility="public", **fields):
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            cals = await world(db)
            event = await published(
                db,
                cals[{"public": "U", "internal": "I", "private": "P"}[visibility]],
                title="Talk",
                starts_at=TEN,
                **fields,
            )
            for user in users:
                await bulk_follows(db, event.id, [user], lead)
            ids = {"event": event.id, "cal": {k: c.id for k, c in cals.items()}}
            await db.commit()
    return ids


async def run_tick(app, state, now=NOW, settings=SETTINGS, runtime=None):
    async def factory_for(db):
        return runtime if runtime is not None else web_runtime(app)

    with no_tenant():
        return await tick.reminders_async(
            state.session_factory, runtime_factory=factory_for, now=now, settings=settings
        )


async def weekly(db, cals, start, end):
    return await seed_series(
        db, cals["U"], "FREQ=WEEKLY", start, end, tz="UTC", status="published", title="Weekly"
    )


async def ledger(state, tenant="default"):
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            return [
                (r.recipient_id, r.state)
                for r in (await db.execute(select(ReminderSent))).scalars()
            ]
