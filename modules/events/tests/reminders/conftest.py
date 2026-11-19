"""Fixtures the reminder send tests share."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.core.tenancy import tenant_scope

from tests.reminders.support import published, world

START = datetime(2026, 7, 1, 10, tzinfo=UTC)


@pytest.fixture
async def cast(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            cals = await world(db)
            event = await published(db, cals["U"], title="Talk", starts_at=START)
            await db.commit()
    return db_state, event.id, event.revision
