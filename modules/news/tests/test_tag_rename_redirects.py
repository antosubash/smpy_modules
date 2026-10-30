"""A renamed tag's old address keeps working, and a racing rename is a 409 (#174).

Split from ``test_tag_management`` at the seam between "what the screen does"
and "what that does to the world outside it": the public archive URL the old
slug was published at, and the unique index that settles a race the
application check cannot see.
"""

from __future__ import annotations

import pytest
from conftest import ROLE_EDITOR
from news import tag_service
from news.constants import ROUTE_PREFIX_API
from news.models import NewsTag, NewsTagRedirect
from sqlalchemy import select
from stub_auth import stub_user
from tenant_app import as_tenant, multi_client

pytestmark = pytest.mark.asyncio

TAGS = f"{ROUTE_PREFIX_API}/taxonomy/tags"


async def _create(client, name: str, headers: dict | None = None) -> dict:
    response = await client.post(TAGS, json={"name": name}, headers=headers or {})
    assert response.status_code == 201, response.text
    return response.json()


async def _rename(client, tag_id: int, name: str, headers: dict | None = None):
    return await client.put(f"{TAGS}/{tag_id}", json={"name": name}, headers=headers or {})


class TestOldAddress:
    async def test_the_old_tag_url_301s_to_the_new_one(self, editor_public_client) -> None:
        tag = await _create(editor_public_client, "Urbn")
        assert (await _rename(editor_public_client, tag["id"], "Urban")).status_code == 200

        response = await editor_public_client.get("/news/tag/urbn?page=2")

        assert response.status_code == 301
        assert response.headers["location"] == "/news/tag/urban?page=2"
        assert (await editor_public_client.get("/news/tag/urban")).status_code == 200

    async def test_a_chain_of_renames_is_one_hop(self, editor_public_client) -> None:
        tag = await _create(editor_public_client, "One")
        await _rename(editor_public_client, tag["id"], "Two")
        await _rename(editor_public_client, tag["id"], "Three")

        for old in ("one", "two"):
            response = await editor_public_client.get(f"/news/tag/{old}")
            assert response.headers["location"] == "/news/tag/three"

    async def test_renaming_back_leaves_no_loop(self, editor_public_client) -> None:
        tag = await _create(editor_public_client, "Here")
        await _rename(editor_public_client, tag["id"], "There")
        await _rename(editor_public_client, tag["id"], "Here")

        assert (await editor_public_client.get("/news/tag/here")).status_code == 200
        moved = await editor_public_client.get("/news/tag/there")
        assert moved.headers["location"] == "/news/tag/here"

    async def test_every_language_redirects_under_its_own_prefix(
        self, bilingual_public_client
    ) -> None:
        async with bilingual_public_client.db_state.session_factory() as db:
            tag = await tag_service.get_or_create(db, "Baum")
            await tag_service.rename(db, tag, "Wald")
            await db.commit()

        response = await bilingual_public_client.get("/de/news/tag/baum")

        assert response.status_code == 301
        assert response.headers["location"] == "/de/news/tag/wald"

    async def test_a_merged_tags_url_follows_it(self, editor_public_client) -> None:
        source = await _create(editor_public_client, "Trees")
        target = await _create(editor_public_client, "Forest")
        merged = await editor_public_client.post(
            f"{TAGS}/{target['id']}/merge", json={"source_id": source["id"]}
        )
        assert merged.status_code == 200, merged.text

        response = await editor_public_client.get("/news/tag/trees")
        assert response.headers["location"] == "/news/tag/forest"

    async def test_deleting_the_tag_drops_its_redirects(self, editor_public_client) -> None:
        tag = await _create(editor_public_client, "Old")
        await _rename(editor_public_client, tag["id"], "Gone")
        assert (await editor_public_client.delete(f"{TAGS}/{tag['id']}")).status_code == 204

        # An empty archive, as for any tag nobody uses — not a hop to nowhere.
        assert (await editor_public_client.get("/news/tag/old")).status_code == 200
        async with editor_public_client.db_state.session_factory() as db:
            assert (await db.execute(select(NewsTagRedirect))).all() == []


async def test_a_rename_that_loses_the_race_is_409_not_500(editor_client, monkeypatch) -> None:
    """Both requests pass the check; the unique index stops the second.

    Simulated by switching the check off, which is exactly the state the loser
    is in: it read before the winner wrote.
    """
    await _create(editor_client, "Urban")
    rural = await _create(editor_client, "Rural")

    async def no_clash(*_args, **_kwargs):
        return None

    monkeypatch.setattr(tag_service, "_clash", no_clash)
    response = await _rename(editor_client, rural["id"], "urban")

    assert response.status_code == 409, response.text
    assert "already exists" in response.json()["detail"]
    async with editor_client.db_state.session_factory() as db:
        names = set((await db.execute(select(NewsTag.name))).scalars().all())
        redirects = (await db.execute(select(NewsTagRedirect))).all()
    assert names == {"Urban", "Rural"}
    assert redirects == []


@pytest.mark.unbound_tenant
async def test_another_tenants_tag_cannot_be_renamed_or_deleted() -> None:
    a, b = as_tenant("acme"), as_tenant("globex")
    async for mt in multi_client(stub_user((ROLE_EDITOR,)), mount_public=True):
        tag = await _create(mt, "Mine", a)

        assert (await _rename(mt, tag["id"], "Hijacked", b)).status_code == 404
        assert (await mt.delete(f"{TAGS}/{tag['id']}", headers=b)).status_code == 404
        listed = (await mt.get(TAGS, headers=a)).json()["items"]
        assert [t["name"] for t in listed] == ["Mine"]

        # A redirect is the renaming tenant's alone.
        await _create(mt, "Old", b)
        own = await _create(mt, "Old", a)
        assert (await _rename(mt, own["id"], "New", a)).status_code == 200
        assert (await mt.get("/news/tag/old", headers=a)).status_code == 301
        assert (await mt.get("/news/tag/old", headers=b)).status_code == 200


async def test_a_new_tag_at_a_retired_slug_takes_it_back(editor_public_client) -> None:
    """Re-creating "Urbn" after it was renamed gives the slug to the new tag;
    the old redirect must not resurface once that tag is gone."""
    tag = await _create(editor_public_client, "Urbn")
    await _rename(editor_public_client, tag["id"], "Urban")
    again = await _create(editor_public_client, "Urbn")
    assert (await editor_public_client.get("/news/tag/urbn")).status_code == 200

    assert (await editor_public_client.delete(f"{TAGS}/{again['id']}")).status_code == 204
    assert (await editor_public_client.get("/news/tag/urbn")).status_code == 200
