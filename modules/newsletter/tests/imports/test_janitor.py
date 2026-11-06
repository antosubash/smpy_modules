"""The hourly import janitor (R6, R14, D2): expire the unapplied, relaunch the lost, per tenant."""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from celery.canvas import Signature
from sm_newsletter.imports.constants import LEASE, STAGED_TTL
from sm_newsletter.imports.janitor import janitor_async

from tests.imports.world import FIELDS, job_of, staged, upload
from tests.support.app import build_app
from tests.support.import_world import (
    NOW,
    SUB,
    export,
    people,
    queue,
    set_job,
    staged_count,
)
from tests.support.records_seed import seed_list

pytestmark = pytest.mark.unbound_tenant

LATER = NOW + timedelta(days=2)


@pytest_asyncio.fixture
async def world(tmp_path, monkeypatch):
    _app, st = await build_app(file=tmp_path / "janitor.db")
    await seed_list(st, "default", fields=FIELDS)
    sent: list[tuple] = []

    def record(self, args=None, kwargs=None, **options):
        sent.append((self.args, options))

    monkeypatch.setattr(Signature, "apply_async", record)
    yield st, sent
    await st.engine.dispose()


async def exists(st, jid, tenant="default") -> bool:
    from sm_newsletter.core.tenancy import tenant_scope
    from sm_newsletter.models import ImportJob
    from sqlalchemy import select

    with tenant_scope(tenant):
        async with st.session_factory() as s:
            stmt = select(ImportJob.id).where(ImportJob.id == jid)
            return (await s.execute(stmt)).first() is not None


async def test_expires_old_staged_and_failed(world):
    st, sent = world
    old = await staged(st, upload(SUB, people("s", 2)))
    failed = await staged(st, upload(SUB, people("f", 2)))
    await set_job(st, failed, status="failed", error_code="import_failed")
    summary = await janitor_async(st.session_factory, now=NOW + STAGED_TTL + timedelta(seconds=1))
    assert summary == {"expired": 2, "relaunched": 0, "failed": 0}
    assert not await exists(st, old) and not await exists(st, failed)
    assert await staged_count(st, old) == 0 and await staged_count(st, failed) == 0
    assert sent == []


async def test_relaunches_stale_queued_and_expired_running(world):
    st, sent = world
    queued_ = await export(st)
    released = await export(st)
    owned = await export(st)
    await set_job(st, released, status="running", lease_owner=None, lease_until=NOW)
    await set_job(st, owned, status="running", lease_owner="dead", lease_until=NOW)
    now = NOW + LEASE + timedelta(seconds=1)
    summary = await janitor_async(st.session_factory, now=now)
    assert summary == {"expired": 0, "relaunched": 3, "failed": 0}
    assert sorted(a for a, _ in sent) == sorted(
        [("default", queued_), ("default", released), ("default", owned)]
    )
    assert all(o == {"queue": "newsletter"} for _, o in sent)
    assert await exists(st, queued_)


async def test_leaves_fresh_and_done(world):
    st, sent = world
    fresh_staged = await staged(st, upload(SUB, people("s", 1)))
    fresh_queued = await export(st)
    held = await export(st)
    await set_job(st, held, status="running", lease_owner="live", lease_until=NOW + LEASE)
    just_released = await export(st)
    await set_job(st, just_released, status="running", lease_owner=None, lease_until=NOW)
    done = await export(st)
    await set_job(st, done, status="done")
    summary = await janitor_async(st.session_factory, now=NOW + timedelta(minutes=1))
    assert summary == {"expired": 0, "relaunched": 0, "failed": 0}
    assert sent == []
    for jid in (fresh_staged, fresh_queued, held, just_released, done):
        assert await exists(st, jid)
    assert (await job_of(st, done)).status == "done"


async def test_janitor_per_tenant(world):
    st, sent = world
    await seed_list(st, "other", fields=FIELDS)
    a_old = await staged(st, upload(SUB, people("a", 1)))
    b_old = await staged(st, upload(SUB, people("b", 1)), tenant="other")
    b_queued = await export_for(st, "other")
    summary = await janitor_async(st.session_factory, now=LATER)
    assert summary == {"expired": 2, "relaunched": 1, "failed": 0}
    assert not await exists(st, a_old) and not await exists(st, b_old, "other")
    assert sent == [(("other", b_queued), {"queue": "newsletter"})]


async def export_for(st, tenant: str) -> int:
    from tests.imports.world import staged as stage_in

    jid = await stage_in(st, upload(SUB, people("q", 2)), tenant=tenant)
    await queue(st, jid, tenant)
    return jid
