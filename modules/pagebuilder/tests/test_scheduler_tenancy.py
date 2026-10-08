"""The scheduler tick runs once per tenant, each in its own tenant context."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from pagebuilder import scheduler
from pagebuilder.models import Page, PageRevision, PageStatus
from pagebuilder.service import PagesService
from pg_support import make_db_state
from simple_module_db import current_tenant_id, tenant_context
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


async def _env():
    state = await make_db_state()
    state.tenant_strict = True
    factory = async_sessionmaker(
        state.engine, expire_on_commit=False, sync_session_class=state.sync_session_class
    )
    return state, factory


async def _seed(factory, tenant: str, slug: str, **kw) -> int:
    with tenant_context(tenant):
        async with factory() as session:
            page = Page(title=slug, slug=slug, draft_data={"content": ["hi"]}, **kw)
            session.add(page)
            await session.commit()
            return page.id


def _past() -> datetime:
    return datetime.now(UTC) - timedelta(minutes=1)


async def test_each_tenant_publishes_under_its_own_tenant() -> None:
    state, factory = await _env()
    try:
        a = await _seed(factory, "acme", "a", publish_at=_past())
        b = await _seed(factory, "globex", "b", publish_at=_past())
        await scheduler._tick(factory)
        for tenant, pid in (("acme", a), ("globex", b)):
            with tenant_context(tenant):
                async with factory() as session:
                    page = await session.get(Page, pid)
                    assert page.status == PageStatus.PUBLISHED
                    assert page.tenant_id == tenant
                    revs = (await session.execute(select(PageRevision))).scalars().all()
                    assert revs and {r.tenant_id for r in revs} == {tenant}
    finally:
        await state.engine.dispose()


async def test_one_failing_tenant_does_not_stop_the_other(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    state, factory = await _env()
    try:
        a = await _seed(factory, "acme", "a", publish_at=_past())
        b = await _seed(factory, "globex", "b", publish_at=_past())
        real = PagesService.process_due

        async def flaky(self, now):
            if current_tenant_id.get() == "acme":
                raise RuntimeError("boom")
            return await real(self, now)

        monkeypatch.setattr(PagesService, "process_due", flaky)
        with caplog.at_level(logging.ERROR, logger=scheduler._log.name):
            await scheduler._tick(factory)
        assert "acme" in caplog.text
        with tenant_context("acme"):
            async with factory() as session:
                assert (await session.get(Page, a)).status == PageStatus.DRAFT
        with tenant_context("globex"):
            async with factory() as session:
                assert (await session.get(Page, b)).status == PageStatus.PUBLISHED
    finally:
        await state.engine.dispose()


async def test_nothing_due_opens_no_tenant_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    state, factory = await _env()
    try:
        await _seed(factory, "acme", "a", publish_at=datetime.now(UTC) + timedelta(days=1))
        calls: list[str] = []

        async def spy(f):
            calls.append("x")

        monkeypatch.setattr(scheduler, "_tick_tenant", spy)
        await scheduler._tick(factory)
        assert calls == []
    finally:
        await state.engine.dispose()


async def test_expired_trash_is_purged_per_tenant() -> None:
    state, factory = await _env()
    try:
        old = datetime.now(UTC) - timedelta(days=60)
        pid = await _seed(factory, "acme", "gone", deleted_at=old)
        await scheduler._tick(factory)
        with tenant_context("acme"):
            async with factory() as session:
                assert await session.get(Page, pid) is None
    finally:
        await state.engine.dispose()
