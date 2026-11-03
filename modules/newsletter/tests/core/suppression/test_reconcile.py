"""The hourly reconcile: records' opt-outs re-read into the suppression store.

A platform pass, run by the worker with no tenant bound, so every test here is
``unbound_tenant``; the helpers bind the tenant they read or seed themselves.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from simple_module_db import finalize_session
from simple_module_db.listeners import TenantIsolationError
from sm_newsletter.core.suppression import reconcile, suppress, suppressed
from sm_newsletter.core.suppression.reconcile import reconcile_async
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression
from sm_records.core import events
from sm_records.core.tenancy import tenant_scope as records_scope
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service
from sm_records.records.services.errors import NotFound
from sqlalchemy import select

from tests.support.records_seed import LIST, seed_list, seed_subscriber

pytestmark = pytest.mark.unbound_tenant

T = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
ADA, BOB, CY = "ada@example.org", "bob@example.org", "cy@example.org"


async def _rows(db_state, tenant: str = "default") -> list[tuple[str, str, str]]:
    """``(reason, list_type_key, source)`` of every row in ``tenant``."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            stmt = select(Suppression).order_by(Suppression.id)
            return [
                (r.reason, r.list_type_key, r.source) for r in (await s.execute(stmt)).scalars()
            ]


async def _suppressed(db_state, tenant: str, *emails: str) -> set[str]:
    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            return await suppressed(s, tenant_id=tenant, emails=list(emails))


async def test_reconcile_suppresses_unsubscribed(db_state):
    await seed_list(db_state, "default")
    await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    await seed_subscriber(db_state, "default", BOB, "unsubscribed")
    await seed_subscriber(db_state, "default", CY, "confirmed")

    result = await reconcile_async(db_state.session_factory, now=T)

    assert result == {"lists": 1, "suppressed": 2, "failed": 0}
    assert await _rows(db_state) == [("unsubscribed", LIST, "reconcile")] * 2
    assert await _suppressed(db_state, "default", ADA, BOB, CY) == {ADA, BOB}


async def test_reconcile_is_idempotent(db_state):
    await seed_list(db_state, "default")
    await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    first = await reconcile_async(db_state.session_factory, now=T)
    second = await reconcile_async(db_state.session_factory, now=T)
    assert first["suppressed"] == 1
    assert second == {"lists": 1, "suppressed": 0, "failed": 0}
    assert len(await _rows(db_state)) == 1


async def test_reconcile_never_clears(db_state):
    """A confirmed subscriber's bounce, and an opt-out records no longer holds,
    both survive: the reconcile only adds."""
    await seed_list(db_state, "default")
    await seed_subscriber(db_state, "default", ADA, "confirmed")
    async with db_state.session_factory() as s:
        await suppress(s, tenant_id="default", email=ADA, reason="hard_bounce", source="send")
        await suppress(
            s,
            tenant_id="default",
            email=ADA,
            reason="unsubscribed",
            source="admin",
            list_type_key=LIST,
        )
        await finalize_session(s)

    result = await reconcile_async(db_state.session_factory, now=T)

    assert result == {"lists": 1, "suppressed": 0, "failed": 0}
    assert await _rows(db_state) == [("hard_bounce", "", "send"), ("unsubscribed", LIST, "admin")]


async def test_reconcile_pages(db_state, monkeypatch):
    monkeypatch.setattr(reconcile, "PAGE_SIZE", 1)
    await seed_list(db_state, "default")
    for email in (ADA, BOB, CY):
        await seed_subscriber(db_state, "default", email, "unsubscribed")
    result = await reconcile_async(db_state.session_factory, now=T)
    assert result == {"lists": 1, "suppressed": 3, "failed": 0}
    assert await _suppressed(db_state, "default", ADA, BOB, CY) == {ADA, BOB, CY}


async def test_reconcile_includes_the_trash(db_state):
    """A trashed opt-out is still an opt-out."""
    await seed_list(db_state, "default")
    await seed_subscriber(db_state, "default", ADA, "unsubscribed", trashed=True)
    result = await reconcile_async(db_state.session_factory, now=T)
    assert result == {"lists": 1, "suppressed": 1, "failed": 0}


async def test_reconcile_with_no_lists(db_state):
    assert await reconcile_async(db_state.session_factory, now=T) == {
        "lists": 0,
        "suppressed": 0,
        "failed": 0,
    }


async def test_one_bad_list_does_not_stop_others(db_state, monkeypatch, caplog):
    """Tenant ``a`` (walked first) has two lists and its first one fails: the
    second list and the next tenant are still reconciled."""
    await seed_list(db_state, "a", "alpha")
    await seed_list(db_state, "a", "news")
    await seed_list(db_state, "b", "news")
    await seed_subscriber(db_state, "a", BOB, "unsubscribed", "alpha")
    await seed_subscriber(db_state, "a", ADA, "unsubscribed", "news")
    await seed_subscriber(db_state, "b", CY, "unsubscribed", "news")
    real = reconcile.iter_subscribers

    async def flaky(session, *, tenant_id, type_key, **kw):
        if (tenant_id, type_key) == ("a", "alpha"):
            raise RuntimeError("records is having a bad day")
        return await real(session, tenant_id=tenant_id, type_key=type_key, **kw)

    monkeypatch.setattr(reconcile, "iter_subscribers", flaky)
    with caplog.at_level(logging.WARNING, logger=reconcile.__name__):
        result = await reconcile_async(db_state.session_factory, now=T)

    assert result == {"lists": 3, "suppressed": 2, "failed": 1}
    assert await _suppressed(db_state, "a", ADA, BOB) == {ADA}
    assert await _suppressed(db_state, "b", CY) == {CY}
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warned and warned[0].exc_info is not None
    assert "list 'alpha' in tenant a" in warned[0].getMessage()


async def test_a_tenant_whose_lists_cannot_be_read_counts_as_one_failure(db_state, monkeypatch):
    for tenant in ("a", "b"):
        await seed_list(db_state, tenant)
        await seed_subscriber(db_state, tenant, ADA, "unsubscribed")
    real = reconcile.subscription_lists

    async def flaky(session, *, tenant_id):
        if tenant_id == "a":
            raise RuntimeError("boom")
        return await real(session, tenant_id=tenant_id)

    monkeypatch.setattr(reconcile, "subscription_lists", flaky)
    result = await reconcile_async(db_state.session_factory, now=T)
    assert result == {"lists": 1, "suppressed": 1, "failed": 1}
    assert await _suppressed(db_state, "b", ADA) == {ADA}


async def test_reconcile_under_a_bound_tenant_is_refused(db_state):
    """A request never enumerates every tenant: the pass does not unbind the
    caller's tenant, so records' enumeration refuses it and nothing is written."""
    await seed_list(db_state, "default")
    await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    with tenant_scope("default"), pytest.raises(TenantIsolationError):
        await reconcile_async(db_state.session_factory, now=T)
    assert await _rows(db_state) == []


async def test_a_failed_tenant_enumeration_propagates(db_state, monkeypatch):
    async def down(session):
        raise RuntimeError("database down")

    monkeypatch.setattr(reconcile, "subscription_list_tenants", down)
    with pytest.raises(RuntimeError, match="database down"):
        await reconcile_async(db_state.session_factory, now=T)


async def test_reconcile_tenant_isolation(db_state):
    for tenant in ("a", "b"):
        await seed_list(db_state, tenant)
    await seed_subscriber(db_state, "a", ADA, "unsubscribed")
    await seed_subscriber(db_state, "b", ADA, "confirmed")

    result = await reconcile_async(db_state.session_factory, now=T)

    assert result == {"lists": 2, "suppressed": 1, "failed": 0}
    assert await _rows(db_state, "a") == [("unsubscribed", LIST, "reconcile")]
    assert await _rows(db_state, "b") == []


async def test_each_write_runs_under_its_own_tenant(db_state, monkeypatch):
    """Two tenants, one address: every ``suppress_many`` call is made with its
    ``tenant_id`` already bound, and neither tenant's row lands in the other."""
    from simple_module_db import current_tenant_id

    for tenant in ("a", "b"):
        await seed_list(db_state, tenant)
        await seed_subscriber(db_state, tenant, ADA, "unsubscribed")
    calls: list[tuple[str | None, str]] = []
    real = reconcile.suppress_many

    async def spy(session, *, tenant_id, **kw):
        calls.append((current_tenant_id.get(), tenant_id))
        return await real(session, tenant_id=tenant_id, **kw)

    monkeypatch.setattr(reconcile, "suppress_many", spy)
    result = await reconcile_async(db_state.session_factory, now=T)

    assert result == {"lists": 2, "suppressed": 2, "failed": 0}
    assert sorted(calls) == [("a", "a"), ("b", "b")]
    async with db_state.session_factory() as s:
        stmt = select(Suppression.__table__.c.tenant_id).order_by("tenant_id")
        assert list((await s.execute(stmt)).scalars()) == ["a", "b"]
    assert await _rows(db_state, "a") == [("unsubscribed", LIST, "reconcile")]
    assert await _rows(db_state, "b") == [("unsubscribed", LIST, "reconcile")]


async def test_lost_event_trash_reconcile_purge_still_suppressed(db_state):
    """Amendment 6: an opt-out whose event was lost, then trashed, is picked up
    by the reconcile from the trash - and purging the record afterwards does
    not take the suppression with it."""
    await seed_list(db_state, "default")
    uuid = await seed_subscriber(db_state, "default", ADA, "unsubscribed", trashed=True)

    await reconcile_async(db_state.session_factory, now=T)
    assert await _rows(db_state) == [("unsubscribed", LIST, "reconcile")]

    with records_scope("default"):
        async with db_state.session_factory() as db:
            rtype = await type_service.get_type(db, LIST)
            record = await record_service.get_deleted_record(db, rtype, uuid)
            await record_service.hard_delete_record(db, rtype, record)
            await events.commit(db)
        async with db_state.session_factory() as db:
            rtype = await type_service.get_type(db, LIST)
            with pytest.raises(NotFound):
                await record_service.get_deleted_record(db, rtype, uuid)

    assert await _rows(db_state) == [("unsubscribed", LIST, "reconcile")]
    assert await _suppressed(db_state, "default", ADA) == {ADA}
    # And the next reconcile neither re-adds nor clears it.
    assert (await reconcile_async(db_state.session_factory, now=T))["suppressed"] == 0
    assert await _suppressed(db_state, "default", ADA) == {ADA}
