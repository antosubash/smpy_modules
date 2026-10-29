"""A released SAVEPOINT fires ``after_commit`` too; it is not the outer commit."""

from __future__ import annotations

from sm_images.ingest import slots
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


async def test_a_savepoint_release_is_not_taken_for_the_outer_commit(monkeypatch):
    released: list[list] = []

    async def release(_factory, acquired):
        released.append(acquired)

    async def finalize(db):  # savepoint released, then the outer transaction rolls back
        await db.execute(text("select 1"))
        nested = await db.begin_nested()
        await nested.commit()
        await db.rollback()

    monkeypatch.setattr(slots, "release_after_rollback", release)
    monkeypatch.setattr(slots, "finalize_session", finalize)
    engine = create_async_engine("sqlite+aiosqlite://")
    async with AsyncSession(engine) as db:
        await slots.finalize_or_release(db, object(), ["op"])
    await engine.dispose()
    assert released == [["op"]]
