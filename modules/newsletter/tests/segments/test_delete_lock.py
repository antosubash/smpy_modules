"""Deleting a segment and pointing a draft at it serialise on the segment's row.

``delete_segment`` checks for a draft naming the segment and then deletes it;
without a lock a concurrent PATCH could set a draft's audience to the segment
in between. Both take ``SELECT … FOR UPDATE`` on the segment row (rendered on
Postgres, a no-op on SQLite), which is what these tests pin: the statement each
path issues carries the lock.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants
from sm_newsletter.models import Segment
from sqlalchemy import Select, event

from tests.support.app import build_app
from tests.support.records_seed import TAGS, seed_list

API = constants.ROUTE_PREFIX_API
PERMS = [constants.PERM_VIEW, constants.PERM_EDIT, constants.PERM_RECORDS_VIEW]
CALLER = {"x-perms": ",".join(PERMS)}
RULES = [{"field": "tags", "op": "any", "value": ["vip"]}]
SEGMENT_TABLE = Segment.__table__  # ty: ignore[unresolved-attribute]


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, "default", fields=[TAGS])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        seg = {"name": "VIPs", "list_type_key": "news", "rules": RULES}
        res = await client.post(f"{API}/segments", json=seg, headers=CALLER)
        assert res.status_code == 201, res.text
        yield client, state, res.json()["id"]
    await state.engine.dispose()


@contextlib.contextmanager
def _locked_segment_reads(state: Any) -> Iterator[list[Select]]:
    """Every ``SELECT … FOR UPDATE`` on the segment table run meanwhile."""
    seen: list[Select] = []

    def on_execute(conn, clause, multiparams, params, execution_options):
        if (
            isinstance(clause, Select)
            and clause._for_update_arg is not None
            and SEGMENT_TABLE in clause.get_final_froms()
        ):
            seen.append(clause)

    engine = state.engine.sync_engine
    event.listen(engine, "before_execute", on_execute)
    try:
        yield seen
    finally:
        event.remove(engine, "before_execute", on_execute)


async def test_delete_locks_the_segment_row(built):
    client, state, sid = built
    with _locked_segment_reads(state) as seen:
        res = await client.delete(f"{API}/segments/{sid}", headers=CALLER)
    assert res.status_code == 204, res.text
    assert seen, "delete_segment read the segment without FOR UPDATE"


async def test_a_draft_patch_naming_the_segment_locks_it(built):
    client, state, sid = built
    created = await client.post(
        f"{API}/campaigns", json={"name": "c", "list_type_key": "news"}, headers=CALLER
    )
    assert created.status_code == 201, created.text
    url = f"{API}/campaigns/{created.json()['id']}"
    with _locked_segment_reads(state) as seen:
        body = {"expected_revision": 1, "audience": f"segment:{sid}"}
        res = await client.patch(url, json=body, headers=CALLER)
    assert res.status_code == 200, res.text
    assert seen, "the PATCH resolved the segment without FOR UPDATE"


async def test_a_count_does_not_lock(built):
    client, state, sid = built
    with _locked_segment_reads(state) as seen:
        url = f"{API}/lists/news/audience-count"
        res = await client.get(url, params={"audience": f"segment:{sid}"}, headers=CALLER)
    assert res.status_code == 200, res.text
    assert seen == []
