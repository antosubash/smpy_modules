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

import pytest_asyncio
from sm_images.clock import utcnow
from sm_images.errors import TooManyOpenUploads
from sm_images.ingest import admission
from sm_images.models import Collection, UploadSession, UploadStatus
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope

from tests.pg_support import arm_reset, make_db_state

CAP = 2
OPENS = 5
NO_BILLING = SimpleNamespace(state=SimpleNamespace())


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


async def _open(state, collection_id: uuid.UUID) -> bool:
    with tenant_scope(DEFAULT_TENANT):
        async with state.session_factory() as db:
            try:
                await admission.admit(NO_BILLING, db, DEFAULT_TENANT, 10, cap=CAP)
            except TooManyOpenUploads:
                await db.rollback()
                return False
            await asyncio.sleep(0.05)  # the window a racing open would slip through
            db.add(
                UploadSession(
                    collection_id=collection_id,
                    image_id=uuid.uuid4(),
                    storage_key=f"k/{uuid.uuid4().hex}",
                    backend_upload_id="u",
                    size=10,
                    content_type="image/jpeg",
                    status=UploadStatus.OPEN,
                    expires_at=utcnow() + timedelta(hours=1),
                )
            )
            await db.commit()
            return True


async def test_concurrent_opens_never_exceed_the_cap(state):
    cid = await _collection(state)
    admitted = await asyncio.gather(*(_open(state, cid) for _ in range(OPENS)))
    assert sum(admitted) == CAP
    with tenant_scope(DEFAULT_TENANT):
        async with state.session_factory() as db:
            assert (await admission.open_uploads(db, DEFAULT_TENANT))[0] == CAP
