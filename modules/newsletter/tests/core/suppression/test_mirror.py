"""Records' ``SubscriptionChanged`` mirrored into the suppression store."""

from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest
from simple_module_core.events import EventBus
from simple_module_db import finalize_session
from sm_newsletter.core.suppression import email_hash, suppress
from sm_newsletter.core.suppression.mirror import apply
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression
from sm_newsletter.module import NewsletterModule
from sm_records.contracts.events import SubscriptionChanged
from sm_records.contracts.newsletter import subscribers_by_uuid, unsubscribe
from sm_records.core.settings import RecordsSettings
from sqlalchemy import select

from tests.support.records_seed import LIST, seed_list, seed_subscriber

ADA = "ada@example.org"


def _event(uuid: str, before: str | None, after: str, tenant: str = "default"):
    return SubscriptionChanged(
        type_key=LIST, tenant_id=tenant, uuid=uuid, status_before=before, status_after=after
    )


async def _rows(db_state, tenant: str = "default") -> list[tuple[str, str, str]]:
    """``(reason, list_type_key, source)`` of every row in ``tenant``."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            rows = (await s.execute(select(Suppression).order_by(Suppression.id))).scalars()
            return [(r.reason, r.list_type_key, r.source) for r in rows]


async def _seed_rows(db_state, *reasons: str, now=None) -> None:
    async with db_state.session_factory() as s:
        for reason in reasons:
            await suppress(
                s,
                tenant_id="default",
                email=ADA,
                reason=reason,
                source="admin",
                list_type_key=LIST if reason == "unsubscribed" else "",
                now=now,
            )
        await finalize_session(s)


async def _confirmed_at(db_state, uuid: str):
    async with db_state.session_factory() as s:
        hits = await subscribers_by_uuid(s, tenant_id="default", type_key=LIST, uuids=[uuid])
    return hits[uuid].confirmed_at


def _wired(db_state) -> EventBus:
    bus = EventBus()
    app = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=db_state, event_bus=bus)))
    NewsletterModule().register_event_handlers(bus, app)
    return bus


async def _unsubscribe(db_state, bus, uuid: str) -> bool:
    async with db_state.session_factory() as s:
        wrote = await unsubscribe(
            s,
            tenant_id="default",
            type_key=LIST,
            uuid=uuid,
            unless_confirmed_after=None,
            settings=RecordsSettings(),
            bus=bus,
        )
        await finalize_session(s)
    return wrote


async def test_unsubscribe_event_suppresses(db_state):
    await seed_list(db_state, "default")
    u = await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    got = await apply(_event(u, "confirmed", "unsubscribed"), db_state.session_factory)
    assert got == "suppressed"
    assert await _rows(db_state) == [("unsubscribed", LIST, "records_event")]


async def test_repeat_unsubscribe_event_still_suppressed(db_state):
    await seed_list(db_state, "default")
    u = await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    event = _event(u, "confirmed", "unsubscribed")
    assert await apply(event, db_state.session_factory) == "suppressed"
    assert await apply(event, db_state.session_factory) == "suppressed"
    assert len(await _rows(db_state)) == 1


async def test_confirm_event_clears_but_keeps_complaint(db_state):
    await seed_list(db_state, "default")
    await _seed_rows(db_state, "unsubscribed", "hard_bounce", "complaint")
    u = await seed_subscriber(db_state, "default", ADA, "confirmed")
    assert await apply(_event(u, "pending", "confirmed"), db_state.session_factory) == "cleared"
    assert [r[0] for r in await _rows(db_state)] == ["complaint"]


async def test_confirm_with_nothing_to_clear_still_reports_cleared(db_state):
    """``"cleared"`` means the clear ran, not that it deleted a row."""
    await seed_list(db_state, "default")
    u = await seed_subscriber(db_state, "default", ADA, "confirmed")
    assert await apply(_event(u, "pending", "confirmed"), db_state.session_factory) == "cleared"
    assert await _rows(db_state) == []


async def test_delayed_confirm_keeps_a_newer_bounce(db_state):
    await seed_list(db_state, "default")
    u = await seed_subscriber(db_state, "default", ADA, "confirmed")
    t1 = await _confirmed_at(db_state, u)
    await _seed_rows(db_state, "unsubscribed", now=t1 - timedelta(hours=1))
    await _seed_rows(db_state, "hard_bounce", now=t1 + timedelta(hours=1))
    assert await apply(_event(u, "pending", "confirmed"), db_state.session_factory) == "cleared"
    assert [r[0] for r in await _rows(db_state)] == ["hard_bounce"]


async def test_confirmed_without_a_time_clears_nothing(db_state, monkeypatch):
    from sm_newsletter.core.suppression import mirror

    await seed_list(db_state, "default")
    await _seed_rows(db_state, "hard_bounce")
    u = await seed_subscriber(db_state, "default", ADA, "confirmed")
    real = mirror.subscribers_by_uuid

    async def no_time(*args, **kwargs):
        hits = await real(*args, **kwargs)
        return {k: v.model_copy(update={"confirmed_at": None}) for k, v in hits.items()}

    monkeypatch.setattr(mirror, "subscribers_by_uuid", no_time)
    assert await apply(_event(u, "pending", "confirmed"), db_state.session_factory) == "ignored"
    assert [r[0] for r in await _rows(db_state)] == ["hard_bounce"]


async def test_stale_event_is_ignored(db_state):
    await seed_list(db_state, "default")
    confirmed = await seed_subscriber(db_state, "default", ADA, "confirmed")
    stale = _event(confirmed, "confirmed", "unsubscribed")
    assert await apply(stale, db_state.session_factory) == "ignored"
    assert await _rows(db_state) == []

    left = await seed_subscriber(db_state, "default", "bob@example.org", "unsubscribed")
    await _seed_rows(db_state, "hard_bounce")
    stale = _event(left, "pending", "confirmed")
    assert await apply(stale, db_state.session_factory) == "ignored"
    assert [r[0] for r in await _rows(db_state)] == ["hard_bounce"]


async def test_pending_is_ignored(db_state):
    await seed_list(db_state, "default")
    await _seed_rows(db_state, "unsubscribed")
    u = await seed_subscriber(db_state, "default", ADA, "pending")
    assert await apply(_event(u, None, "pending"), db_state.session_factory) == "ignored"
    assert await _rows(db_state) == [("unsubscribed", LIST, "admin")]


async def test_trashed_unsubscribed_still_mirrored(db_state):
    await seed_list(db_state, "default")
    u = await seed_subscriber(db_state, "default", ADA, "unsubscribed", trashed=True)
    got = await apply(_event(u, "confirmed", "unsubscribed"), db_state.session_factory)
    assert got == "suppressed"
    assert await _rows(db_state) == [("unsubscribed", LIST, "records_event")]


async def test_trashed_confirmed_clears_nothing(db_state):
    await seed_list(db_state, "default")
    await _seed_rows(db_state, "unsubscribed")
    u = await seed_subscriber(db_state, "default", ADA, "confirmed", trashed=True)
    assert await apply(_event(u, "pending", "confirmed"), db_state.session_factory) == "ignored"
    assert len(await _rows(db_state)) == 1


async def test_unknown_uuid_is_harmless(db_state):
    await seed_list(db_state, "default")
    got = await apply(_event("no-such-uuid", None, "unsubscribed"), db_state.session_factory)
    assert got == "ignored"
    assert await _rows(db_state) == []


async def test_not_a_list_is_ignored(db_state):
    from sm_records.core import events
    from sm_records.records.services import types as type_service

    async with db_state.session_factory() as s:
        await type_service.create_type(s, key=LIST, label="x", settings=RecordsSettings())
        await events.commit(s)
    got = await apply(_event("u", None, "unsubscribed"), db_state.session_factory)
    assert got == "ignored"


async def test_real_unsubscribe_reaches_the_mirror(db_state):
    bus = _wired(db_state)
    await seed_list(db_state, "default")
    u = await seed_subscriber(db_state, "default", ADA, "confirmed")
    assert await _unsubscribe(db_state, bus, u) is True
    assert await _rows(db_state) == [("unsubscribed", LIST, "records_event")]


async def test_handler_failure_never_breaks_records_write(db_state, caplog):
    class _Broken:
        @property
        def session_factory(self):
            raise RuntimeError("no database")

    bus = EventBus()
    app = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=_Broken(), event_bus=bus)))
    NewsletterModule().register_event_handlers(bus, app)
    await seed_list(db_state, "default")
    u = await seed_subscriber(db_state, "default", ADA, "confirmed")
    with caplog.at_level(logging.WARNING):
        assert await _unsubscribe(db_state, bus, u) is True
    async with db_state.session_factory() as s:
        hits = await subscribers_by_uuid(s, tenant_id="default", type_key=LIST, uuids=[u])
    assert hits[u].status == "unsubscribed"
    mine = [r for r in caplog.records if r.name.startswith("sm_newsletter")]
    assert len(mine) == 1
    assert mine[0].levelno == logging.WARNING
    assert mine[0].exc_info is not None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_no_app_registers_nothing(db_state):
    bus = EventBus()
    NewsletterModule().register_event_handlers(bus, None)
    await seed_list(db_state, "default")
    u = await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    await bus.publish(_event(u, "confirmed", "unsubscribed"))
    assert await _rows(db_state) == []


@pytest.mark.unbound_tenant
async def test_tenant_isolation(db_state):
    for tenant in ("a", "b"):
        await seed_list(db_state, tenant)
    ua = await seed_subscriber(db_state, "a", ADA, "unsubscribed")
    await seed_subscriber(db_state, "b", ADA, "unsubscribed")
    got = await apply(_event(ua, "confirmed", "unsubscribed", "a"), db_state.session_factory)
    assert got == "suppressed"
    assert await _rows(db_state, "a") == [("unsubscribed", LIST, "records_event")]
    assert await _rows(db_state, "b") == []
    with tenant_scope("a"):
        async with db_state.session_factory() as s:
            row = (await s.execute(select(Suppression))).scalar_one()
    assert (row.tenant_id, row.email_hash) == ("a", email_hash(ADA))
