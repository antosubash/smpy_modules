"""A campaign's audience over HTTP: a half-set one is never stored (Codex P1)."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.records_seed import seed_list

BASE = f"{constants.ROUTE_PREFIX_API}/campaigns"
VIEW = {"x-perms": constants.PERM_VIEW}
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}


@pytest_asyncio.fixture
async def client():
    app, state = await build_app()
    await seed_list(state, "default")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await state.engine.dispose()


async def test_half_set_audience_is_never_stored(client):
    """A kind without its value ("tag:", "segment:") is refused, and the stored
    audience and revision stay as they were: the editor's unfinished choice can
    never reach the server as a different audience."""
    res = await client.post(BASE, json={"name": "c", "list_type_key": "news"}, headers=EDIT)
    assert res.status_code == 201, res.text
    cid = res.json()["id"]
    for audience in ("tag:", "segment:"):
        res = await client.patch(
            f"{BASE}/{cid}", json={"expected_revision": 1, "audience": audience}, headers=EDIT
        )
        assert (res.status_code, res.json()["code"]) == (422, "invalid_audience"), audience
    got = (await client.get(f"{BASE}/{cid}", headers=VIEW)).json()
    assert (got["audience"], got["revision"]) == ("all", 1)
