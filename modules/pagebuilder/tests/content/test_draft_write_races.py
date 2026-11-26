"""Two connections cannot both save a draft using the same base version."""

import asyncio

import pytest
from pagebuilder.content.service.pages import PagesService
from pagebuilder.contracts.schemas import PageCreate, PageUpdate
from pagebuilder.core.errors import PageConflict
from pg_support import make_db_state
from sqlalchemy import event

from tests.support import app as harness

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def racing_client(tmp_path, monkeypatch):
    # An in-memory StaticPool shares one transaction and cannot test locking.
    monkeypatch.setattr(
        harness, "make_db_state", lambda: make_db_state(file=tmp_path / "draft-races.db")
    )
    async for client in harness._client_fixture(
        tmp_path, requires_auth=True, csrf_protect=False, inject_user=True
    ):
        yield client


@pytest.mark.parametrize("side_action", [None, "schedule", "publish"])
async def test_only_one_writer_uses_the_loaded_token(racing_client, side_action):
    client = racing_client
    created = await client.post("/api/pagebuilder/pages", json={
        "slug": "racing", "title": "Original", "draft_data": {"content": []},
    })
    assert created.status_code == 201, created.text
    page = created.json()
    path = f"/api/pagebuilder/pages/{page['id']}"
    token = {"expected_updated_at": page["updated_at"]}
    if side_action:
        body = (
            {**token, "publish_at": "2099-01-01T09:00:00Z"}
            if side_action == "schedule" else token
        )
        other = client.post(f"{path}/{side_action}", json=body)
    else:
        other = client.put(path, json={**token, "title": "Second editor"})
    first, second = await asyncio.wait_for(asyncio.gather(
        client.put(path, json={**token, "title": "First editor"}), other,
    ), timeout=15)
    assert sorted([first.status_code, second.status_code]) == [200, 409], (
        first.text, second.text
    )
    refused = first if first.status_code == 409 else second
    assert refused.json()["code"] == "page_conflict"
    stored = (await client.get(path)).json()
    if first.status_code == 200:
        assert stored["title"] == "First editor"
        assert stored["status"] == "draft"
        assert stored["publish_at"] is None
    elif side_action is None:
        assert stored["title"] == "Second editor"
    else:
        assert stored["title"] == "Original"


async def test_waiting_writer_refreshes_its_cached_page_after_the_lock(tmp_path):
    state = await make_db_state(file=tmp_path / "waiting-writer.db")
    started = asyncio.Event()

    def lock_started(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE pagebuilder_pages SET updated_at="):
            started.set()

    try:
        async with state.session_factory() as first, state.session_factory() as second:
            page = await PagesService(first).create(PageCreate(title="Base", slug="wait"))
            page_id, token = page.id, page.updated_at
            await first.commit()
            # Both writers have read this version before either tries to save.
            cached = await PagesService(second).get_page(page_id)
            assert cached.title == "Base"
            await PagesService(first).update(page_id, PageUpdate(
                title="Winner", expected_updated_at=token,
            ))
            # The first writer holds the transaction open. The second signals
            # just before its lock statement enters the driver and must wait.
            event.listen(state.engine.sync_engine, "before_cursor_execute", lock_started)
            waiting = asyncio.create_task(PagesService(second).update(page_id, PageUpdate(
                title="Loser", expected_updated_at=token,
            )))
            await asyncio.wait_for(started.wait(), timeout=3)
            assert not waiting.done()
            await first.commit()
            with pytest.raises(PageConflict):
                await asyncio.wait_for(waiting, timeout=5)
            assert cached.title == "Winner"
            await second.rollback()
        async with state.session_factory() as check:
            assert (await PagesService(check).get_page(page_id)).title == "Winner"
    finally:
        event.remove(state.engine.sync_engine, "before_cursor_execute", lock_started)
        await state.engine.dispose()
