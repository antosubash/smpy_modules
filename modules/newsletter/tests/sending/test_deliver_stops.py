"""Delivering one recipient (Task 6): what stops a campaign rather than a row.

A list that is gone pauses the campaign (``list_unavailable``, as freeze does),
and a cancel that lands during the SMTP call never leaves the in-flight row
``queued`` in a cancelled campaign.
"""

from __future__ import annotations

import pytest
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.campaigns.lifecycle import split_paused
from sm_newsletter.sending import deliver as delivering
from sm_newsletter.sending.classify import Verdict
from sm_newsletter.sending.deliver import Step
from sm_newsletter.sending.transport import DeliveryResult
from sm_records.core import events
from sm_records.core.tenancy import tenant_scope as records_scope
from sm_records.records.services import types as type_service

from tests.support.campaign_world import campaign_row
from tests.support.deliver_world import (
    attempts,
    counters,
    deliver,
    in_other_session,
    one_row,
    sending_campaign,
)
from tests.support.fake_transport import FakeTransport
from tests.support.freeze_world import world
from tests.support.records_seed import set_list_kind
from tests.support.sending import NOW, T

LIST_PAUSE = Step(False, Verdict("pause", True, pause_code="list_unavailable"))


@pytest.fixture
async def state(tmp_path):
    _, db_state, _ = await world(tmp_path)
    yield db_state
    await db_state.engine.dispose()


async def _delete_list(state, n: int) -> None:
    with records_scope(T):
        async with state.session_factory() as db:
            rtype = await type_service.get_type(db, "news")
            await type_service.delete_type(db, rtype, confirm_record_count=n)
            await events.commit(db)


async def _assert_list_paused(state, cid, smtp) -> None:
    campaign = await campaign_row(state, T, cid)
    assert campaign.status == "paused"
    assert split_paused(campaign.paused_reason) == ("list_unavailable", None)
    row = await one_row(state, cid)
    assert (row.status, row.attempts, row.lease_until) == ("queued", 0, None)
    assert smtp.sent == [] and await attempts(state) == []


async def test_deleted_list_pauses_the_campaign(state):
    cid, _ = await sending_campaign(state)
    await _delete_list(state, 1)
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) == LIST_PAUSE
    await _assert_list_paused(state, cid, smtp)


@pytest.mark.parametrize("seen_listed", [False, True], ids=["checked", "raced"])
async def test_list_no_longer_a_list_pauses_the_campaign(state, monkeypatch, seen_listed):
    cid, _ = await sending_campaign(state)
    await set_list_kind(state, T, "news", "form")
    if seen_listed:  # de-listed between the list check and the subscriber read

        async def still_listed(session, **kw):
            return ["news"]

        monkeypatch.setattr(delivering, "subscription_lists", still_listed)
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) == LIST_PAUSE
    await _assert_list_paused(state, cid, smtp)


def _cancel_during_smtp(state, cid):
    async def cancel(_msg) -> None:
        async def write(db) -> None:
            await lifecycle.cancel(db, tenant_id=T, campaign_id=cid, roles=[], now=NOW)

        await in_other_session(state, write)

    return cancel


@pytest.mark.parametrize(
    "reply",
    [
        DeliveryResult("rejected", 451, "4.3.0 Try again later", "data"),
        DeliveryResult("rejected", 554, "5.4.5 Daily sending quota exceeded", "data"),
    ],
    ids=["retry", "pause"],
)
async def test_cancel_during_smtp_ends_the_row_cancelled(state, reply):
    cid, (email,) = await sending_campaign(state)
    smtp = FakeTransport({email: reply}, on_send=_cancel_during_smtp(state, cid))

    step = await deliver(state, cid, smtp)

    assert step is not None and step.spent
    row = await one_row(state, cid)
    assert (row.status, row.attempts, row.lease_until) == (
        "cancelled",
        int(reply.code == 451),
        None,
    )
    assert (await campaign_row(state, T, cid)).status == "cancelled"
    assert [a.outcome for a in await attempts(state)] == ["rejected"]


async def test_cancel_during_an_accepted_send_still_records_it(state):
    cid, _ = await sending_campaign(state)
    smtp = FakeTransport(on_send=_cancel_during_smtp(state, cid))

    await deliver(state, cid, smtp)

    assert (await one_row(state, cid)).status == "sent"
    assert (await counters(state, cid))["sent_count"] == 1


async def test_retry_while_paused_stays_queued(state):
    """A pause during the SMTP call is still a live campaign: the row waits."""
    cid, (email,) = await sending_campaign(state)
    soft = DeliveryResult("rejected", 451, "4.3.0 Try again later", "data")

    async def pause(_msg) -> None:
        async def write(db) -> None:
            await lifecycle.pause(db, tenant_id=T, campaign_id=cid, roles=[], now=NOW)

        await in_other_session(state, write)

    await deliver(state, cid, FakeTransport({email: soft}, on_send=pause))

    assert (await one_row(state, cid)).status == "queued"
