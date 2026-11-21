"""A subscription's items are never reminded: a follow needs a native event."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar
from sqlalchemy import select

from tests.reminders.tick_support import ledger, run_tick, seed
from tests.support.subscriptions import seed_item, seed_subscription

pytestmark = pytest.mark.usefixtures("mailbox")
ONE = "ExtOneOff-9f3"


@pytest.mark.unbound_tenant
async def test_the_reminder_tick_mails_ours_only(host, mailbox):
    app, state = host
    ids = await seed(state)
    with tenant_scope("default"):
        async with state.session_factory() as db:
            cal = (
                await db.execute(select(Calendar).where(Calendar.id == ids["cal"]["U"]))
            ).scalar_one()
            sub = await seed_subscription(db, cal, public=True)
            await seed_item(db, sub, "x", datetime(2026, 7, 1, 10, tzinfo=UTC), title=ONE)
            await db.commit()
    got = await run_tick(app, state)
    assert got["sent"] == 1
    (mail,) = mailbox.messages
    assert ONE not in mail.subject + mail.text + (mail.html or "")
    assert await ledger(state) == [("v", "sent")]
