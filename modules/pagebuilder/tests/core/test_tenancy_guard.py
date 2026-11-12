"""The fail-closed guard — ``pagebuilder.core.tenancy.install_guard`` (#335).

The same guard records, images and newsletter install: with it on the session
class, pagebuilder ORM work with no tenant bound raises instead of reading every
tenant's rows. These pin that it covers every pagebuilder table, that startup
installs it, and that each entry point that runs with nothing bound — the
scheduler's tenant enumeration, the boot-time media scan, the search contract —
still works under it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pagebuilder.contracts.search import search_media, search_pages
from pagebuilder.core.tenancy import (
    TenantIsolationError,
    TenantUnbound,
    all_tenants,
    install_guard,
    tenant_scope,
)
from pagebuilder.core.tenancy._guard import is_guarded, owned
from pagebuilder.media.media_files import warn_on_orphaned_media
from pagebuilder.models import Base, MediaAsset, Page, PageStatus
from pagebuilder.scheduling import scheduler
from pg_support import make_db_state
from sqlalchemy import func, select
from sqlmodel import SQLModel

from tests.support.app import _build_app

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def guarded():
    state = await make_db_state()
    install_guard(state.sync_session_class)
    install_guard(state.sync_session_class)  # idempotent
    try:
        yield state
    finally:
        await state.engine.dispose()


async def _seed(state, tenant: str, slug: str, **kw) -> int:
    with tenant_scope(tenant):
        async with state.session_factory() as session:
            page = Page(title=slug, slug=slug, draft_data={}, **kw)
            session.add(page)
            session.add(
                MediaAsset(
                    filename=f"{tenant}-{slug}.png",
                    original_filename=f"{slug}.png",
                    content_type="image/png",
                )
            )
            await session.commit()
            return page.id


def test_every_pagebuilder_table_is_guarded():
    """Every table in pagebuilder's metadata belongs to a class the guard owns."""
    guarded = {
        mapper.local_table.name
        for mapper in SQLModel._sa_registry.mappers
        if owned(mapper.class_)
    }
    assert guarded and guarded == set(Base.metadata.tables)


async def test_an_unbound_read_or_write_is_refused(guarded):
    await _seed(guarded, "acme", "a")
    assert is_guarded(guarded.sync_session_class)
    async with guarded.session_factory() as session:
        with pytest.raises(TenantUnbound, match="Page"):
            await session.execute(select(Page))
        with pytest.raises(TenantUnbound):
            await session.execute(select(func.count(MediaAsset.id)))
    async with guarded.session_factory() as session:
        session.add(Page(title="x", slug="x", draft_data={}, tenant_id="acme"))
        with pytest.raises(TenantUnbound, match="written with no tenant bound"):
            await session.flush()


async def test_a_tagged_read_passes_and_a_bound_one_is_still_filtered(guarded):
    await _seed(guarded, "acme", "a")
    await _seed(guarded, "globex", "b")
    async with guarded.session_factory() as session:
        stmt = all_tenants(select(Page.tenant_id).order_by(Page.tenant_id))
        assert (await session.execute(stmt)).scalars().all() == ["acme", "globex"]
    with tenant_scope("acme"):
        async with guarded.session_factory() as session:
            assert (await session.execute(select(Page.slug))).scalars().all() == ["a"]


async def test_the_scheduler_tick_runs_under_the_guard(guarded):
    past = datetime.now(UTC) - timedelta(minutes=1)
    ids = {t: await _seed(guarded, t, t, publish_at=past) for t in ("acme", "globex")}
    await scheduler._tick(guarded.session_factory)
    for tenant, page_id in ids.items():
        with tenant_scope(tenant):
            async with guarded.session_factory() as session:
                page = await session.get(Page, page_id)
                assert page is not None and page.status == PageStatus.PUBLISHED


async def test_the_boot_media_scan_runs_under_the_guard(guarded, tmp_path):
    await _seed(guarded, "acme", "a")
    await _seed(guarded, "globex", "b")
    assert await warn_on_orphaned_media(guarded.session_factory, tmp_path) == 2


async def test_the_search_contract_binds_the_tenant_it_is_given(guarded):
    """Unbound, it binds the named tenant; bound to another one, it refuses."""
    await _seed(guarded, "acme", "alpha")
    await _seed(guarded, "globex", "alpine")
    async with guarded.session_factory() as session:
        hits, total = await search_pages(
            session, "%alp%", tenant_id="acme", include_drafts=True, limit=10
        )
        assert ([h.slug for h in hits], total) == (["alpha"], 1)
        media, count = await search_media(session, "%al%", tenant_id="globex", limit=10)
        assert ([m.filename for m in media], count) == (["globex-alpine.png"], 1)
    with tenant_scope("acme"):
        async with guarded.session_factory() as session:
            with pytest.raises(TenantIsolationError):
                await search_pages(
                    session, "%alp%", tenant_id="globex", include_drafts=True, limit=10
                )


async def test_startup_installs_the_guard(tmp_path):
    app, cleanup = await _build_app(
        tmp_path, requires_auth=False, csrf_protect=False, inject_user=False
    )
    try:
        assert is_guarded(app.state.sm.db.sync_session_class)
    finally:
        await cleanup()
