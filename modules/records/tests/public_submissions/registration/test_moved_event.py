"""A moved event's registrations follow its new date: "started", the registrant's list and the
retention window come from events' resolved start, not the start captured at submit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event
from sm_records.core import constants
from sm_records.public_submissions import retention
from sqlalchemy import update

from tests.public_submissions.registration.test_mine import URL, Directory, me
from tests.support.app_harness import roles
from tests.support.harness_auth import ROLE_VIEWER
from tests.support.public_submissions_support import update as update_type
from tests.support.registration_http import (
    TYPE,
    follow,
    reg_config,
    reg_links,
    register_confirmed,
    regs,
    seat_counts,
)

pytestmark = pytest.mark.usefixtures("reg_site")
OLD = datetime(2099, 7, 1, 8, tzinfo=UTC)


async def move(site, start):
    event_id = __import__("uuid").UUID(site.event["event_id"])
    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            await db.execute(
                update(Event)
                .where(Event.id == event_id)
                .values(starts_at=start, ends_at=start + timedelta(hours=1))
            )
            await db.commit()


async def test_moved_later_the_registration_can_still_be_cancelled_after_the_old_date(reg_site):
    await register_confirmed(reg_site)
    token = reg_links(reg_site.outbox.sent[0])["cancel"]["t"]
    await move(reg_site, datetime.now(UTC) + timedelta(days=30))
    await _stale_snapshot(
        reg_site, datetime.now(UTC) - timedelta(days=1)
    )  # the old date has passed
    resp = await follow(reg_site, "cancel", token)
    assert resp.status_code == 200
    assert (await regs(reg_site))[0]["data"]["sm_status"] == "cancelled"
    assert await seat_counts(reg_site) == (0, 0)


async def test_moved_earlier_started_is_true_from_the_new_date(reg_site):
    await register_confirmed(reg_site)
    token = reg_links(reg_site.outbox.sent[0])["cancel"]["t"]
    await move(reg_site, datetime.now(UTC) - timedelta(hours=2))  # already started
    await follow(reg_site, "cancel", token)
    assert (await regs(reg_site))[0]["data"]["sm_status"] == "registered"
    assert await seat_counts(reg_site) == (1, 1)


async def test_my_registrations_shows_the_moved_one(reg_site):
    await register_confirmed(reg_site, "test@example.com")
    await move(reg_site, datetime.now(UTC) + timedelta(days=30))
    await _stale_snapshot(reg_site, datetime.now(UTC) - timedelta(days=1))
    me(reg_site)
    got = (await reg_site.get(URL, headers=roles(ROLE_VIEWER))).json()
    assert len(got["items"]) == 1
    assert Directory  # the fake account directory used by "my registrations"


async def test_retention_keeps_a_registration_whose_event_moved_later(reg_site):
    await update_type(
        reg_site,
        TYPE,
        public_submissions=reg_config(
            double_opt_in=False, consent={"required": True, "text": {"en": "ok"}}, retention_days=30
        ),
    )
    await register_confirmed(reg_site, consent=True)
    later = datetime.now(UTC) + timedelta(days=100)
    await move(reg_site, later + timedelta(days=60))  # well after the sweep
    await _stale_snapshot(reg_site, later - timedelta(days=90))  # the snapshot says it is due
    settings = getattr(reg_site.app.state, constants.PACKAGE).settings
    done = await retention.sweep(reg_site.db_state.session_factory, settings, now=later)
    assert done is not None and done.purged == 0
    assert len(await regs(reg_site)) == 1 and await seat_counts(reg_site) == (1, 1)


async def _stale_snapshot(site, start):
    """Rewrite the record's stored occurrence start, as an old submission would carry."""
    from sm_records.models import tables_for
    from sm_records.records.services.types import get_type
    from sqlalchemy import update as sa_update

    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            rtype = await get_type(db, TYPE)
            cls = tables_for(rtype).record
            row = (await db.execute(__import__("sqlalchemy").select(cls))).scalars().first()
            data = dict(row.data)
            data["sm_occurrence_start"] = start.isoformat()
            await db.execute(sa_update(cls).where(cls.id == row.id).values(data=data))
            await db.commit()


async def test_confirmation_refreshes_the_snapshot_to_the_moved_date(reg_site):
    from tests.support.registration_http import confirm_record, register

    await register(reg_site, "ada@example.org")
    (record,) = await regs(reg_site)
    new = (datetime.now(UTC) + timedelta(days=40)).replace(microsecond=0)
    await move(reg_site, new)
    assert (await confirm_record(reg_site, record)).status_code == 200
    (after,) = await regs(reg_site)
    stored = datetime.fromisoformat(after["data"]["sm_occurrence_start"])
    assert abs((stored.replace(tzinfo=stored.tzinfo or UTC) - new).total_seconds()) < 1


async def test_my_registrations_are_ordered_by_the_events_current_start(reg_site):
    from tests.public_submissions.registration.test_mine import sign_up
    from tests.support.registration_http import seed_event

    soon = datetime.now(UTC) + timedelta(days=10)
    first = await seed_event(
        reg_site.db_state, uid="o1@x", starts_at=soon, ends_at=soon + timedelta(hours=1)
    )
    second = await seed_event(
        reg_site.db_state,
        uid="o2@x",
        starts_at=soon + timedelta(days=5),
        ends_at=soon + timedelta(days=5, hours=1),
    )
    a = await sign_up(reg_site, address="test@example.com", event=first)
    b = await sign_up(reg_site, address="test@example.com", event=second)
    me(reg_site)
    order = [
        i["uuid"] for i in (await reg_site.get(URL, headers=roles(ROLE_VIEWER))).json()["items"]
    ]
    assert order == [a["uuid"], b["uuid"]]
    reg_site.event = first
    await move(reg_site, soon + timedelta(days=30))  # the first event now comes last
    got = (await reg_site.get(URL, headers=roles(ROLE_VIEWER))).json()["items"]
    assert [i["uuid"] for i in got] == [b["uuid"], a["uuid"]]
