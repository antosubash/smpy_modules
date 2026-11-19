"""More reminders due than a tick may send: nothing is lost silently, nobody is starved."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest
from simple_module_core.mail import install_mail_sender
from simple_module_db.query_filter import EngineTenancy, bind_engine_policy
from sm_events.core.constants import reminders_limits as limits
from sm_events.core.tenancy import tenant_scope
from sm_events.models import ReminderSent
from sm_events.reminders import stats
from sqlalchemy import select

from tests.reminders.support import ORIGIN
from tests.reminders.tick_support import TEN, Mailbox, run_tick, seed
from tests.support.app import Directory, build_app
from tests.support.tokens import install_members

LEAD = 15  # catch-up 5 minutes: the event at 10:00 is due 9:45 and stale after 9:50
TICKS = [TEN - timedelta(minutes=15) + timedelta(minutes=i) for i in range(14)]  # 9:45-9:58


async def _world(users: dict, *, tenants: dict[str, set[str]]):
    app, state = await build_app(multi=True)
    bind_engine_policy(state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    app.state.user_directory = Directory(users, dict.fromkeys(users, ("viewer",)))
    app.state.sm.settings.public_base_url = ORIGIN
    install_members(app, tenants)
    box = Mailbox()
    install_mail_sender(box)
    return app, state, box


async def _rows(state, tenant: str) -> list[tuple[str, str, str | None]]:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            rows = (await db.execute(select(ReminderSent))).scalars()
            return [(r.recipient_id, r.state, r.code) for r in rows]


@pytest.mark.unbound_tenant
async def test_a_thousand_followers_on_a_short_lead_are_all_mailed_and_others_are_served():
    users = {f"u{i}": (f"u{i}@example.com", f"U{i}", True) for i in range(1000)}
    users["b1"] = ("b1@example.com", "B", True)
    app, state, box = await _world(
        users, tenants={"a": {u for u in users if u != "b1"}, "b": {"b1"}}
    )
    try:
        await seed(state, users=tuple(u for u in users if u != "b1"), lead=LEAD, tenant="a")
        await seed(state, users=("b1",), lead=LEAD, tenant="b")
        first = await run_tick(app, state, now=TICKS[0])
        assert [r for r in await _rows(state, "b") if r[1] == "sent"], (
            "b is served in the first tick"
        )
        assert first["sent"] <= limits.REMINDER_SEND_BUDGET
        for now in TICKS[1:]:
            await run_tick(app, state, now=now)
        rows = await _rows(state, "a")
        by = Counter(state_ for _u, state_, _c in rows)
        missing = sorted(set(users) - {u for u, *_ in rows} - {"b1"})
        assert by == {"sent": 1000}, (by, missing)  # the install budget carried the whole event
        assert len({u for u, *_ in rows}) == 1000
        assert len(box.messages) == 1001  # one per follower and b's, no duplicates
        assert len({m.to for m in box.messages}) == 1001
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_what_cannot_be_sent_in_time_is_recorded_as_too_late_never_mailed(monkeypatch):
    monkeypatch.setattr(limits, "REMINDER_TENANT_BUDGET", 20)
    monkeypatch.setattr(limits, "REMINDER_SEND_BUDGET", 40)
    users = {f"u{i}": (f"u{i}@example.com", f"U{i}", True) for i in range(400)}
    app, state, box = await _world(users, tenants={"a": set(users)})
    try:
        await seed(state, users=tuple(users), lead=LEAD, tenant="a")
        for now in TICKS:
            await run_tick(app, state, now=now)
        rows = await _rows(state, "a")
        assert len(rows) == 400 == len({u for u, *_ in rows})  # one row each, none missing
        sent = [r for r in rows if r[1] == "sent"]
        late = [r for r in rows if r[1] == "failed"]
        assert {c for *_x, c in late} == {"too_late"}
        assert len(sent) + len(late) == 400 and late
        assert len(box.messages) == len(sent)  # a too_late row never mails
        async with state.session_factory() as db, _Scope("a"):
            got = await stats.counts(db, now=TEN)
        assert got.failed == {"too_late": len(late)} and got.sent == len(sent)
        mine = await _count_for(state, "a", "u7")
        assert mine in (1,)
    finally:
        await state.engine.dispose()


class _Scope:
    def __init__(self, tenant: str):
        self._cm = tenant_scope(tenant)

    async def __aenter__(self):
        return self._cm.__enter__()

    async def __aexit__(self, *exc):
        return self._cm.__exit__(*exc)


async def _count_for(state, tenant: str, user: str) -> int:
    return len([r for r in await _rows(state, tenant) if r[0] == user])


@pytest.mark.unbound_tenant
async def test_a_follow_made_after_the_reminder_was_due_gets_no_too_late_row():
    from sm_events.models import Event, EventFollow
    from sqlalchemy import update

    from tests.reminders.support import bulk_follows

    users = {"v": ("v@example.com", "V", True)}
    app, state, box = await _world(users, tenants={"a": {"v"}})
    try:
        await seed(state, users=(), lead=LEAD, tenant="a")
        for now in TICKS[:11]:  # 9:45 to 9:55: nobody follows yet
            await run_tick(app, state, now=now)
        with tenant_scope("a"):
            async with state.session_factory() as db:  # joins at 9:56, after the 9:45 due time
                event = (await db.execute(select(Event))).scalars().first()
                await bulk_follows(db, event.id, ["v"], LEAD)
                late = TICKS[11]
                await db.execute(update(EventFollow.__table__).values(created_at=late))
                await db.commit()
        for now in TICKS[11:]:
            await run_tick(app, state, now=now)
        assert await _rows(state, "a") == []
        assert box.messages == []
    finally:
        await state.engine.dispose()
