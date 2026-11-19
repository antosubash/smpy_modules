"""The beat: one pass for a single tenant, claim-arbitrated and bounded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_core.mail import ConsoleMailSender, install_mail_sender, reset_mail_sender
from simple_module_db import no_tenant
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Event, OccurrenceOverride
from sm_events.reminders import tick
from sm_events.reminders.runtime import web_runtime

from tests.reminders.support import bulk_follows, world
from tests.reminders.tick_support import (
    NOW,
    SETTINGS,
    TEN,
    ledger,
    run_tick,
    seed,
    weekly,
)

pytestmark = pytest.mark.usefixtures("mailbox")


@pytest.mark.unbound_tenant
async def test_end_to_end_one_mail(host, mailbox):
    app, state = host
    await seed(state)
    got = await run_tick(app, state)
    assert (got["sent"], got["failed"], got["tenants"]) == (1, 0, 1)
    (mail,) = mailbox.messages
    assert (
        mail.to == "v@example.com" and "Talk" in mail.subject and mail.html and "10:00" in mail.text
    )
    assert await ledger(state) == [("v", "sent")]


@pytest.mark.unbound_tenant
@pytest.mark.parametrize(
    "case",
    ["unpublished", "event_cancelled", "occurrence_cancelled", "trashed_event", "trashed_calendar",
     "made_private", "no_view_role", "inactive", "unverified"],
)  # fmt: skip
async def test_access_matrix_at_send(host, mailbox, case):
    app, state = host
    user = "a" if case == "no_view_role" else "v"
    visibility = "internal" if case == "made_private" else "public"
    ids = await seed(state, users=(user,), visibility=visibility)
    directory = app.state.user_directory
    with tenant_scope("default"):
        async with state.session_factory() as db:
            event = await db.get(Event, ids["event"])
            if case == "unpublished":
                event.status = "draft"
            elif case == "event_cancelled":
                event.cancelled = True
            elif case == "occurrence_cancelled":
                event.rrule = None  # a one-off has no occurrences to cancel: cancel the event
                event.cancelled = True
            elif case == "trashed_event":
                await db.delete(event)
            elif case == "trashed_calendar":
                await db.delete(await db.get(Calendar, event.calendar_id))
            elif case == "made_private":
                (await db.get(Calendar, event.calendar_id)).visibility = "private"
            await db.commit()
    if case == "inactive":
        directory.users["v"] = ("v@example.com", "V", False)
    if case == "unverified":
        directory.verified["v"] = False
    got = await run_tick(app, state)
    assert mailbox.messages == [] and got["sent"] == 0
    assert await ledger(state) == []


@pytest.mark.unbound_tenant
async def test_a_cancelled_series_occurrence_is_not_reminded(host, mailbox):
    app, state = host
    with tenant_scope("default"):
        async with state.session_factory() as db:
            cals = await world(db)
            event = await weekly(db, cals, "2026-06-24T10:00", "2026-06-24T11:00")
            await bulk_follows(db, event.id, ["v"])
            db.add(OccurrenceOverride(event_id=event.id, original_start=TEN, kind="cancelled"))
            await db.commit()
    assert (await run_tick(app, state))["sent"] == 0 and mailbox.messages == []


@pytest.mark.unbound_tenant
@pytest.mark.parametrize(
    "what", ["disabled", "no_transport", "console", "no_base_url", "no_runtime"]
)
async def test_disabled_or_unavailable_sends_nothing(host, mailbox, what):
    app, state = host
    await seed(state)
    settings, runtime = SETTINGS, None
    if what == "disabled":
        settings = EventsSettings(reminders_enabled=False)
    elif what == "no_transport":
        reset_mail_sender()
    elif what == "console":
        install_mail_sender(ConsoleMailSender())
    elif what == "no_base_url":
        app.state.sm.settings.public_base_url = ""

    async def nobody(db):
        return None

    if what == "no_runtime":
        got = await tick.reminders_async(
            state.session_factory, runtime_factory=nobody, now=NOW, settings=settings
        )
    else:
        got = await run_tick(app, state, settings=settings, runtime=runtime)
    assert got["sent"] == 0 and mailbox.messages == []
    assert await ledger(state) == []
    if what != "disabled":
        assert got["unavailable"] == 1


@pytest.mark.unbound_tenant
async def test_redelivered_tick_sends_nothing(host, mailbox):
    app, state = host
    await seed(state)
    assert (await run_tick(app, state))["sent"] == 1
    again = await run_tick(app, state)
    # already in the ledger, so it is not even a candidate: nothing rendered, nothing claimed
    assert (again["sent"], again["taken"]) == (0, 0) and len(mailbox.messages) == 1
    assert (await run_tick(app, state, now=NOW + timedelta(seconds=30)))["sent"] == 0


@pytest.mark.unbound_tenant
async def test_late_beat_catchup_then_stale(host, mailbox):
    app, state = host
    await seed(state)
    assert (await run_tick(app, state, now=NOW + timedelta(minutes=10)))[
        "sent"
    ] == 1  # 15 min grace
    other = await seed(state, users=("u1",), tenant="default") if False else None
    assert other is None
    assert (await run_tick(app, state, now=NOW + timedelta(minutes=20)))["sent"] == 0
    assert len(mailbox.messages) == 1


@pytest.mark.unbound_tenant
async def test_a_missed_ticks_never_flood(host, mailbox):
    """Beat down for an hour: when it returns only what is still inside the catch-up goes."""
    app, state = host
    await seed(state, users=tuple(f"u{i}" for i in range(5)))
    assert (await run_tick(app, state, now=NOW + timedelta(hours=1)))["sent"] == 0  # started: never
    assert (await run_tick(app, state, now=NOW + timedelta(minutes=16)))["sent"] == 0  # stale
    assert mailbox.messages == []


@pytest.mark.unbound_tenant
async def test_a_moved_occurrence_says_so(host, mailbox):
    app, state = host
    with tenant_scope("default"):
        async with state.session_factory() as db:
            cals = await world(db)
            event = await weekly(db, cals, "2026-06-17T10:00", "2026-06-17T11:00")
            await bulk_follows(db, event.id, ["v"])
            moved_to = TEN + timedelta(minutes=30)
            db.add(
                OccurrenceOverride(
                    event_id=event.id, original_start=datetime(2026, 7, 8, 10, tzinfo=UTC),
                    kind="moved", starts_at=moved_to, ends_at=moved_to + timedelta(hours=1),
                )
            )  # fmt: skip
            await db.commit()
    got = await run_tick(app, state, now=NOW + timedelta(minutes=30))
    texts = [m.text for m in mailbox.messages]
    # The regular 10:00 instance is 30 minutes late (stale: never sent); the moved one, now at
    # 10:30, is exactly due and says where it came from. The old time is never reminded.
    assert got["sent"] == 1 and "moved" in texts[0].lower() and "10:30" in texts[0]


@pytest.mark.unbound_tenant
async def test_settings_are_read_the_way_a_worker_reads_them(host, monkeypatch):
    app, state = host
    seen = []

    def stored():
        seen.append(1)
        return EventsSettings(reminders_enabled=False)

    monkeypatch.setattr(tick, "_stored_settings", stored)

    async def factory(db):
        return web_runtime(app)

    with no_tenant():
        got = await tick.reminders_async(state.session_factory, runtime_factory=factory, now=NOW)
    assert seen == [1] and got["sent"] == 0
