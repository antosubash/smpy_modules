"""The note and the collapse of failure detail follow the effective policy (the saver's right AND
the install switch), and the flag is only ever set while the switch is on."""

from __future__ import annotations

import pytest
from sm_events.core.settings import EventsSettings
from sm_events.feeds.subscriptions import rules, service
from sm_events.models import Subscription
from sm_events.web.schemas.subscriptions import SubscriptionIn, SubscriptionPatch
from sqlalchemy import select

from tests.support.access import principal
from tests.support.calendars import MANAGER
from tests.support.subscriptions import seed_calendar
from tests.support.subscriptions_http import add, app_client, calendar, row, stub_launch

MANAGER_WHO = principal("m", "events.view", "events.manage")
OWNER_WHO = principal("o", "events.view", "events.edit")


def ctx(*, switch: bool, manager: bool):
    return rules.Context(
        EventsSettings(allow_private_subscription_urls=switch),
        is_manager=manager,
        can_publish=False,
        own_hosts={"site.example"},
        public_prefix="/events",
    )


@pytest.mark.parametrize(("switch", "shown"), [(False, False), (True, True)])
async def test_the_note_needs_the_switch(monkeypatch, switch, shown):
    async with app_client(allow_private_subscription_urls=switch) as client:
        stub_launch(monkeypatch)
        cid = await calendar(client)
        made = (await add(client, cid, MANAGER, url="https://a.example.test/a.ics")).json()
        assert made["may_use_internal_addresses"] is shown
        assert (await row(client, made["id"])).may_use_private is shown  # stored only with it on
        listed = (
            await client.get(f"/api/events/calendars/{cid}/subscriptions", headers=MANAGER)
        ).json()
        assert listed[0]["may_use_internal_addresses"] is shown


async def test_saved_before_the_switch_is_not_internal_until_a_manager_saves_it_again(db):
    cal = await seed_calendar(db, "c")
    body = SubscriptionIn(url="https://a.example.test/a.ics", label="Feed")
    sub = await service.create(
        db, MANAGER_WHO, cal.id, body, ctx(switch=False, manager=True), now=cal.created_at
    )
    assert sub.may_use_private is False  # switch off at save time: never stored
    # the switch is turned on later: the old subscription is still not internal-capable
    out = service.to_out(sub, setting_minutes=60, is_manager=True, internal_on=True)
    assert out.may_use_internal_addresses is False
    # a manager saves its address again with the switch on: now it is
    await service.update(
        db, MANAGER_WHO, sub.id, SubscriptionPatch(url="https://a.example.test/a.ics"),
        ctx(switch=True, manager=True), now=cal.created_at,
    )  # fmt: skip
    stored = (await db.execute(select(Subscription).where(Subscription.id == sub.id))).scalar_one()
    assert stored.may_use_private is True
    # ... and a non-manager's save of the same address clears it again
    await service.update(
        db, OWNER_WHO, sub.id, SubscriptionPatch(url="https://a.example.test/a.ics"),
        ctx(switch=True, manager=False), now=cal.created_at,
    )  # fmt: skip
    assert stored.may_use_private is False
