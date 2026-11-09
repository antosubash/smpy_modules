"""Staging: blank rows yield to the event loop, and an ignored file is never parsed."""

from __future__ import annotations

import io

import pytest
import pytest_asyncio
from sm_newsletter.imports import staging

from tests.imports.world import FIELDS, job_of, staged, upload
from tests.support.app import build_app
from tests.support.import_world import SUB
from tests.support.records_seed import seed_list

pytestmark = pytest.mark.unbound_tenant


@pytest_asyncio.fixture
async def state():
    _app, st = await build_app()
    await seed_list(st, "default", fields=FIELDS)
    yield st
    await st.engine.dispose()


async def test_blank_rows_still_yield_to_the_event_loop(state, monkeypatch):
    monkeypatch.setattr(staging, "STAGE_CHUNK", 10)
    calls = []

    async def spy(delay):
        calls.append(delay)

    monkeypatch.setattr(staging.asyncio, "sleep", spy)
    blanks = [["", "", "", ""]] * 95
    jid = await staged(state, upload(SUB, [["a@x.org", "Ada", "L", ""], *blanks]))
    job = await job_of(state, jid)
    assert (job.total, job.invalid, job.errors_total) == (1, 0, 0)  # blanks stay uncounted
    assert len(calls) >= 9  # 96 physical rows at 10 per chunk


async def test_a_broken_ignored_file_does_not_refuse_the_upload(state):
    ignored = "nonsubscribed_members_export.csv"
    jid = await staged(
        state,
        upload(SUB, [["a@x.org", "Ada", "L", ""]]),
        (ignored, io.BytesIO(b"")),
    )
    job = await job_of(state, jid)
    assert job.total == 1
    assert job.files == [
        {"name": SUB, "kind": "subscribed", "rows": 1},
        {"name": ignored, "kind": "ignored", "rows": 0},
    ]
    jid = await staged(
        state,
        upload(SUB, [["a@x.org", "Ada", "L", ""]]),
        upload(ignored, [["z@x.org"]], headers=["Nothing", "Here"]),
    )
    assert [f["kind"] for f in (await job_of(state, jid)).files] == ["subscribed", "ignored"]
