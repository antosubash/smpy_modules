"""``contracts.cards``: the tenant is pinned by the contract, and the read has a fixed cost."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import MissingTenantError, like_contains_pattern
from sm_events.contracts import cards as contract
from sm_events.core.tenancy import TenantIsolationError, tenant_scope
from sm_events.models import Calendar, Visibility
from sm_events.web.endpoints.public import _clock
from sqlalchemy import event as sa_event

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event, seed_series

NOW = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
ANY = like_contains_pattern("")


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(_clock, "now", lambda: NOW)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def _search(db, pattern=ANY, **kw):
    return await contract.search_events(db, tenant_id="default", pattern=pattern, **kw)


@pytest.mark.unbound_tenant
async def test_tenant_pinned_when_unbound(db):
    for tenant in ("a", "b"):
        with tenant_scope(tenant):
            cal = Calendar(slug=tenant, name=tenant, owner_id="o", visibility=Visibility.PUBLIC)
            db.add(cal)
            await db.flush()
            await seed_event(
                db, cal, title=f"{tenant}-event", status="published", starts_at=utc(2026, 8, 1)
            )
    got = await contract.search_events(db, tenant_id="b", pattern=ANY)
    assert [c.title for c in got] == ["b-event"]
    by_id = await contract.get_event_card(db, tenant_id="a", event_id=got[0].id)
    assert by_id is None  # b's event, asked as a


async def test_other_bound_tenant_refused(db):
    with pytest.raises(TenantIsolationError):
        await contract.search_events(db, tenant_id="b", pattern=ANY)
    with pytest.raises(TenantIsolationError):
        await contract.get_event_card(db, tenant_id="b", event_id=uuid.uuid4())


@pytest.mark.parametrize("tenant", ["bad tenant!", "a\n", "", "platform"])
async def test_invalid_tenant_no_sql(db_state, db, tenant):
    seen: list[str] = []

    def spy(_conn, _cursor, statement, *_rest):
        seen.append(statement)

    engine = db_state.engine.sync_engine
    sa_event.listen(engine, "before_cursor_execute", spy)
    try:
        with pytest.raises(ValueError, match="tenant"):
            await contract.search_events(db, tenant_id=tenant, pattern=ANY)
        with pytest.raises(ValueError, match="tenant"):
            await contract.get_event_card(db, tenant_id=tenant, event_id=uuid.uuid4())
    finally:
        sa_event.remove(engine, "before_cursor_execute", spy)
    assert seen == []


async def test_strict_session_unbound_is_empty(db, monkeypatch):
    async def refuse(*_a, **_k):
        raise MissingTenantError("no tenant")

    monkeypatch.setattr(db, "execute", refuse)
    assert await _search(db) == []
    assert await contract.get_event_card(db, tenant_id="default", event_id=uuid.uuid4()) is None


async def _count(db_state, db, call) -> int:
    seen: list[str] = []

    def spy(_conn, _cursor, statement, *_rest):
        seen.append(statement)

    engine = db_state.engine.sync_engine
    sa_event.listen(engine, "before_cursor_execute", spy)
    try:
        await call()
    finally:
        sa_event.remove(engine, "before_cursor_execute", spy)
    return len(seen)


async def test_statement_count_does_not_grow_with_the_events(db_state, db):
    cal = (await seed_calendars(db))["U"]

    async def add(n: int, start: int = 0) -> None:
        for i in range(start, start + n):
            await seed_event(
                db,
                cal,
                title=f"one {i}",
                status="published",
                starts_at=utc(2026, 8, 1) + timedelta(days=i),
            )
            await seed_series(
                db,
                cal,
                "FREQ=WEEKLY;BYDAY=WE",
                "2026-05-06T10:00",
                "2026-05-06T11:00",
                title=f"series {i}",
                status="published",
            )

    await add(2)
    first = await _count(db_state, db, lambda: _search(db, upcoming_only=False, limit=50))
    few = len(await _search(db, upcoming_only=False, limit=50))
    await add(10, start=2)
    many_count = await _count(db_state, db, lambda: _search(db, upcoming_only=False, limit=50))
    many = len(await _search(db, upcoming_only=False, limit=50))
    assert many > few == 4
    assert many_count == first <= 10, (first, many_count)  # 8 today: gate x2, texts, the read
    one_event = (await _search(db, limit=1))[0].id
    single = await _count(
        db_state,
        db,
        lambda: contract.get_event_card(db, tenant_id="default", event_id=one_event),
    )
    assert single <= first
