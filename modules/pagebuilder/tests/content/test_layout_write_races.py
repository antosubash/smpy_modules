"""A waiting layout writer must compare against the row after locking it."""

import asyncio

import pytest
from pagebuilder.content.layout_service import LayoutService
from pagebuilder.contracts.schemas import LayoutUpdate
from pagebuilder.core.errors import LayoutConflict
from pg_support import make_db_state
from sqlalchemy import event

pytestmark = pytest.mark.asyncio


async def test_waiting_writer_refreshes_its_cached_layout_after_the_lock(tmp_path):
    state = await make_db_state(file=tmp_path / "layout-races.db")
    started = asyncio.Event()

    def lock_started(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE pagebuilder_layout SET updated_at="):
            started.set()

    try:
        async with state.session_factory() as first, state.session_factory() as second:
            layout = await LayoutService(first).get()
            token = layout.updated_at
            await first.commit()
            cached = await LayoutService(second).get()
            assert cached.header_data == {}
            await LayoutService(first).update(
                header_data={"content": []},
                version=LayoutUpdate(expected_updated_at=token),
            )
            event.listen(state.engine.sync_engine, "before_cursor_execute", lock_started)
            waiting = asyncio.create_task(LayoutService(second).update(
                footer_data={"content": []},
                version=LayoutUpdate(expected_updated_at=token),
            ))
            await asyncio.wait_for(started.wait(), timeout=3)
            assert not waiting.done()
            await first.commit()
            with pytest.raises(LayoutConflict):
                await asyncio.wait_for(waiting, timeout=5)
            assert cached.header_data == {"content": []}
            assert cached.footer_data == {}
            await second.rollback()
        async with state.session_factory() as check:
            stored = await LayoutService(check).get()
            assert stored.header_data == {"content": []}
            assert stored.footer_data == {}
    finally:
        event.remove(state.engine.sync_engine, "before_cursor_execute", lock_started)
        await state.engine.dispose()
