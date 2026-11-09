import sys
from pathlib import Path

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest_asyncio.fixture
async def factory(tmp_path):
    from sm_analytics.models import Base

    from .pg_support import shared

    pg = shared()
    if pg.USING_POSTGRES:
        pg.arm_reset()
        state = await pg.make_db_state(Base.metadata)
        yield state.session_factory
        await state.engine.dispose()
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/analytics.db")

    @event.listens_for(engine.sync_engine, "connect")
    def constraints(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
