"""The mirror refreshes an existing row's ``created_at`` but never relabels its ``source``.

The first writer's source stands: an opt-out through the unsubscribe page
stays ``unsubscribe_page`` after records' ``SubscriptionChanged`` reaches the
mirror, and only PR 2's refresh (a newer ``created_at``) applies. A brand-new
row still inserts with ``records_event``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_newsletter.core import clock, constants
from sm_newsletter.core.suppression.mirror import apply
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression
from sm_records.contracts.events import SubscriptionChanged
from sqlalchemy import select

from tests.support.records_seed import LIST, seed_list, seed_subscriber
from tests.support.unsub_world import ONE_CLICK, app_with, call, sent_campaign

pytestmark = pytest.mark.unbound_tenant

T = "default"
ADA = "ada@example.org"


async def _row(state) -> tuple[str, object]:
    with tenant_scope(T):
        async with state.session_factory() as db:
            [row] = (await db.execute(select(Suppression))).scalars().all()
            return row.source, row.created_at


def _later(monkeypatch, at) -> None:
    monkeypatch.setattr(clock, "utcnow", lambda: at)


async def test_page_unsubscribe_keeps_its_source_and_the_event_refreshes_created_at(
    monkeypatch,
):
    app, state, events = await app_with()
    try:
        s = await sent_campaign(state, T, ADA)
        assert (await call(app, "POST", s.token, data=ONE_CLICK)).status_code == 200
        source, created = await _row(state)
        assert source == constants.SOURCE_UNSUBSCRIBE_PAGE
        [event] = events
        later = created + timedelta(minutes=5)
        _later(monkeypatch, later)

        assert await apply(event, state.session_factory) == "suppressed"

        assert await _row(state) == (constants.SOURCE_UNSUBSCRIBE_PAGE, later)
    finally:
        await state.engine.dispose()


async def test_a_records_event_row_stays_records_event_on_a_repeated_event(db_state, monkeypatch):
    await seed_list(db_state, T)
    uuid = await seed_subscriber(db_state, T, ADA, "unsubscribed")
    event = SubscriptionChanged(
        type_key=LIST,
        tenant_id=T,
        uuid=uuid,
        status_before="confirmed",
        status_after="unsubscribed",
    )
    assert await apply(event, db_state.session_factory) == "suppressed"
    source, created = await _row(db_state)
    assert source == "records_event"
    later = created + timedelta(minutes=5)
    _later(monkeypatch, later)

    assert await apply(event, db_state.session_factory) == "suppressed"

    assert await _row(db_state) == ("records_event", later)
