"""The unsubscribe cutoff when the message's outcome is unknown (Codex C3).

``sent_at`` is empty for a send whose relay answer was lost, and a campaign can
run for days, so its ``started_at`` is no stand-in for when this person was
mailed: the latest attempt for that send is. A re-confirmation before that
attempt does not shield the address from its own message's link; one after it
still does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Send, SendAttempt
from sm_records.contracts.newsletter import unsubscribe
from sm_records.core import events as records_events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope as records_scope
from sqlalchemy import update

from tests.support.records_seed import LIST, confirm_link, signup
from tests.support.unsub_world import (
    ONE_CLICK,
    Sent,
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
UNSUBSCRIBED = [(constants.REASON_UNSUBSCRIBED, LIST, constants.SOURCE_UNSUBSCRIBE_PAGE)]


@pytest.fixture
async def world():
    app, state, events = await app_with()
    sent = await sent_campaign(state, T, ADA)
    yield app, state, events, sent
    await state.engine.dispose()


async def _reconfirm(app, state, s: Sent) -> None:
    """Left the list some other way (records' own link), then came back."""
    with records_scope(T):
        async with state.session_factory() as db:
            assert await unsubscribe(
                db,
                tenant_id=T,
                type_key=LIST,
                uuid=s.uuid,
                unless_confirmed_after=None,
                settings=RecordsSettings(),
            )
            await records_events.commit(db)
    assert await signup(state, T, ADA, app.state.sm.event_bus) == s.uuid
    assert await confirm_link(state, T, s.uuid, app.state.sm.event_bus) == "confirmed"


async def _outcome_unknown(state, s: Sent, *, attempted_at: datetime) -> None:
    """The send's relay answer was lost: no ``sent_at``, one attempt opened at
    ``attempted_at``."""
    with tenant_scope(T):
        async with state.session_factory() as db:
            await db.execute(
                update(Send)
                .where(Send.id == s.send_id, Send.tenant_id == T)
                .values(status="failed", sent_at=None, error_kind="outcome_unknown")
            )
            db.add(
                SendAttempt(
                    campaign_id=s.campaign_id,
                    send_id=s.send_id,
                    kind="campaign",
                    recipient=ADA,
                    attempted_at=attempted_at,
                    outcome="unknown",
                )
            )
            await finalize_session(db)


async def test_unknown_outcome_after_reconfirmation_unsubscribes(world):
    """Started days ago; the person re-confirmed, and only then was mailed."""
    app, state, events, s = world
    await _reconfirm(app, state, s)
    events.clear()
    await _outcome_unknown(state, s, attempted_at=datetime.now(UTC) + timedelta(seconds=1))

    assert (await call(app, "POST", s.token, data=ONE_CLICK)).status_code == 200
    assert await status_of(state, s) == "unsubscribed"
    assert await suppressions(state, T) == UNSUBSCRIBED
    assert (await counters(state, s))["unsubscribe_count"] == 1
    assert len(events) == 1


async def test_reconfirmation_after_the_unknown_attempt_still_wins(world):
    app, state, events, s = world
    await _outcome_unknown(state, s, attempted_at=datetime.now(UTC) - timedelta(seconds=1))
    await _reconfirm(app, state, s)
    events.clear()

    assert (await call(app, "POST", s.token, data=ONE_CLICK)).status_code == 200
    assert await status_of(state, s) == "confirmed"
    assert await suppressions(state, T) == []
    assert (await counters(state, s))["unsubscribe_count"] == 0
    assert events == []
