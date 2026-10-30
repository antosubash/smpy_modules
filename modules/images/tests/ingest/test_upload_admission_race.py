"""Concurrent opens cannot overshoot ``max_open_uploads_per_tenant`` (S2, Codex P2).

Each open runs in a session of its own (its own connection: a file SQLite
database, or Postgres when ``SM_TEST_DATABASE_URL`` names one), counts, then
inserts its session row after a pause that widens the race. Without the
per-tenant admission lock every open sees the same "slots left" and all of
them get in; with it exactly ``cap`` do.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sm_images.core.clock import utcnow
from sm_images.core.errors import StorageQuotaExceeded, TooManyOpenUploads
from sm_images.core.tenancy import DEFAULT_TENANT, tenant_scope
from sm_images.ingest import admission
from sm_images.models import Collection, UploadSession, UploadStatus

from tests.pg_support import arm_reset, make_db_state

CAP = 2
OPENS = 5


@pytest_asyncio.fixture
async def state(tmp_path):
    arm_reset()
    st = await make_db_state(file=tmp_path / "admission.db")
    yield st
    await st.engine.dispose()


async def _collection(state) -> uuid.UUID:
    with tenant_scope(DEFAULT_TENANT):
        async with state.session_factory() as s:
            row = Collection(slug=f"c-{uuid.uuid4().hex[:8]}", name="C", owner_id="olga")
            s.add(row)
            await s.commit()
            return row.id


def _row(collection_id: uuid.UUID, size: int) -> UploadSession:
    return UploadSession(
        collection_id=collection_id,
        image_id=uuid.uuid4(),
        storage_key=f"k/{uuid.uuid4().hex}",
        backend_upload_id="u",
        size=size,
        content_type="image/jpeg",
        status=UploadStatus.OPEN,
        expires_at=utcnow() + timedelta(hours=1),
    )


async def _open(state, collection_id: uuid.UUID) -> bool:
    with tenant_scope(DEFAULT_TENANT):
        async with state.session_factory() as db:
            try:
                await admission.admit(db, DEFAULT_TENANT, 10, cap=CAP, room=None)
            except TooManyOpenUploads:
                await db.rollback()
                return False
            await asyncio.sleep(0.05)  # the window a racing open would slip through
            db.add(_row(collection_id, 10))
            await db.commit()
            return True


async def test_concurrent_opens_never_exceed_the_cap(state):
    cid = await _collection(state)
    admitted = await asyncio.gather(*(_open(state, cid) for _ in range(OPENS)))
    assert sum(admitted) == CAP
    with tenant_scope(DEFAULT_TENANT):
        async with state.session_factory() as db:
            assert (await admission.open_uploads(db, DEFAULT_TENANT))[0] == CAP


async def test_billing_is_read_before_the_lock_and_never_while_it_is_held(state, gauge):
    """Codex P2: a billing read inside admission would hold the lock's
    connection while checking out another (pool exhaustion). The headroom is
    read by ``prepare``, before any admission connection exists; ``admit``
    itself uses its own session's connection only."""
    gauge.limit = 1000
    pool = state.engine.sync_engine.pool
    real = gauge.check
    during: list[int] = []

    async def check(*a, **k):
        during.append(pool.checkedout())
        return await real(*a, **k)

    gauge.check = check
    app = SimpleNamespace(state=SimpleNamespace(billing_usage=gauge))
    cid = await _collection(state)
    with tenant_scope(DEFAULT_TENANT):
        run = await admission.prepare(app, DEFAULT_TENANT, 600, cap=5)
        assert during == [0]  # nothing held while billing was read
        async with state.session_factory() as db:
            await run(db)
            assert pool.checkedout() == 1  # the admission session's, and only it
            db.add(_row(cid, 600))
            await db.commit()
        assert len(during) == 1  # admit itself never asked billing
        again = await admission.prepare(app, DEFAULT_TENANT, 600, cap=5)
        async with state.session_factory() as db:
            with pytest.raises(StorageQuotaExceeded):
                await again(db)  # 600 open + 600 > the 1000 read before the lock
        assert len(during) == 2
