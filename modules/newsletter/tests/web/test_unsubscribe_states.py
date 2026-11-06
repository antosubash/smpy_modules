"""Which subscriber states a genuine unsubscribe POST suppresses (S9).

A ``pending`` subscriber is never suppressed: records does not unsubscribe one,
and the address has not proven it wants anything. A trashed one is, without a
count: the mail went to that address and its owner asked to stop.
"""

from __future__ import annotations

import pytest
from sm_newsletter.core import constants
from sm_records.core import events as records_events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope as records_scope
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service

from tests.support.records_seed import LIST
from tests.support.unsub_world import (
    ONE_CLICK,
    app_with,
    call,
    counters,
    sent_campaign,
    status_of,
    suppressions,
)

pytestmark = pytest.mark.unbound_tenant

T = "default"
ADA = "ada@example.org"


@pytest.fixture
async def app_state():
    app, state, events = await app_with()
    yield app, state, events
    await state.engine.dispose()


async def test_pending_subscriber_is_not_suppressed(app_state):
    app, state, events = app_state
    s = await sent_campaign(state, T, ADA, status="pending")
    page = (await call(app, "POST", "x.1.1.AAAA")).content
    assert (await call(app, "POST", s.token, data=ONE_CLICK)).content == page
    assert await status_of(state, s) == "pending"
    assert await suppressions(state, T) == []
    assert (await counters(state, s))["unsubscribe_count"] == 0
    assert events == []


async def test_trashed_not_purged_subscriber_is_suppressed(app_state):
    app, state, events = app_state
    s = await sent_campaign(state, T, ADA)
    with records_scope(T):
        async with state.session_factory() as db:
            rtype = await type_service.get_type(db, LIST)
            record = await record_service.get_record(db, rtype, s.uuid)
            await record_service.soft_delete_record(db, rtype, record, settings=RecordsSettings())
            await records_events.commit(db)

    assert (await call(app, "POST", s.token, data=ONE_CLICK)).status_code == 200
    assert await suppressions(state, T) == [
        (constants.REASON_UNSUBSCRIBED, LIST, constants.SOURCE_UNSUBSCRIBE_PAGE)
    ]
    assert (await counters(state, s))["unsubscribe_count"] == 0
    assert events == []
