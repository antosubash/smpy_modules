"""Task 5's intent-ordering rule, end to end, on file-backed SQLite.

One connection per session, as in a host: an intent commits through its own
session, so if it came after the request session's first write it would wait
on that session's writer lock. A batch records every intent before its first
insert (``IngestService.reserve``), so three files land without waiting.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from file_storage.backends.filesystem import FilesystemBackend
from httpx import ASGITransport, AsyncClient
from sm_images.storage.intents import use_session_factory

from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.app_harness import build_app
from tests.support.upload import jpeg, make_collection, post_files


@pytest.mark.skipif(USING_POSTGRES, reason="the hazard is SQLite's single writer")
async def test_batch_on_a_file_database_records_intents_before_writing(tmp_path):
    db_state = await make_db_state(file=tmp_path / "batch.db")
    app, _ = await build_app(tmp_path, db_state)
    app.state.file_storage = SimpleNamespace(backend=FilesystemBackend(tmp_path / "store"))
    use_session_factory(db_state.session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            cid = await make_collection(http)
            files = [(f"{c}.jpg", jpeg(color=c), "image/jpeg") for c in ("red", "green", "blue")]
            got = await post_files(http, cid, files)
            assert got.status_code == 200, got.text
            assert [r["status"] for r in got.json()["results"]] == ["created"] * 3
    finally:
        await db_state.engine.dispose()
