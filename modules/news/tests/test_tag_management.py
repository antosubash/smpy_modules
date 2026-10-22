"""Renaming and deleting a tag through the admin API (#174).

The service-level rules are covered elsewhere (``test_taxonomy``,
``test_tag_link_cleanup``); these pin what the management screen relies on at
the HTTP boundary: a rename keeps the tag's articles and moves its slug, a
clash is a 409 the screen can show, a delete detaches the tag from its articles
without touching them, and only ``news.edit`` may do either.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import tag_service
from news.constants import ROUTE_PREFIX_API
from news.models import NewsArticle
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

TAGS = f"{ROUTE_PREFIX_API}/taxonomy/tags"


async def _tagged_article(client, slug: str, tags: list[str]) -> int:
    async with client.db_state.session_factory() as db:
        article = await make_article(db, slug=slug, title=slug)
        article_id = article.id or 0
    response = await client.put(
        f"{ROUTE_PREFIX_API}/articles/{article_id}/tags", json={"tags": tags}
    )
    assert response.status_code == 200, response.text
    return article_id


async def _tag(client, name: str) -> dict:
    listed = (await client.get(TAGS)).json()["items"]
    return next(t for t in listed if t["name"] == name)


async def test_rename_keeps_the_articles_and_moves_the_slug(editor_client) -> None:
    article_id = await _tagged_article(editor_client, "a", ["Urbn"])
    tag = await _tag(editor_client, "Urbn")

    response = await editor_client.put(f"{TAGS}/{tag['id']}", json={"name": "Urban trees"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "id": tag["id"],
        "name": "Urban trees",
        "slug": "urban-trees",
        "article_count": 1,
    }
    on_article = await editor_client.get(f"{ROUTE_PREFIX_API}/articles/{article_id}/tags")
    assert on_article.json() == ["Urban trees"]


async def test_rename_onto_another_tags_name_is_409(editor_client) -> None:
    await _tagged_article(editor_client, "a", ["Urban", "Rural"])
    rural = await _tag(editor_client, "Rural")

    # A case variant is the same tag to a writer, so it collides too.
    response = await editor_client.put(f"{TAGS}/{rural['id']}", json={"name": "urban"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    assert (await _tag(editor_client, "Rural"))["article_count"] == 1


async def test_rename_of_a_missing_tag_is_404(editor_client) -> None:
    response = await editor_client.put(f"{TAGS}/9999", json={"name": "Ghost"})
    assert response.status_code == 404


async def test_delete_detaches_from_articles_and_keeps_them(editor_client) -> None:
    first = await _tagged_article(editor_client, "a", ["Doomed", "Kept"])
    second = await _tagged_article(editor_client, "b", ["Doomed"])
    doomed = await _tag(editor_client, "Doomed")
    assert doomed["article_count"] == 2

    response = await editor_client.delete(f"{TAGS}/{doomed['id']}")

    assert response.status_code == 204
    names = [t["name"] for t in (await editor_client.get(TAGS)).json()["items"]]
    assert names == ["Kept"]
    for article_id, expected in ((first, ["Kept"]), (second, [])):
        tags = await editor_client.get(f"{ROUTE_PREFIX_API}/articles/{article_id}/tags")
        assert tags.json() == expected
    async with editor_client.db_state.session_factory() as db:
        ids = set((await db.execute(select(NewsArticle.id))).scalars().all())
        assert ids == {first, second}
        assert await tag_service.get(db, doomed["id"]) is None


async def test_delete_of_a_missing_tag_is_404(editor_client) -> None:
    response = await editor_client.delete(f"{TAGS}/9999")
    assert response.status_code == 404


async def test_rename_and_delete_need_the_create_permission(
    editor_client, viewer_client
) -> None:
    """Same gate as creating a tag: ``news.edit`` on the whole router."""
    created = await editor_client.post(TAGS, json={"name": "Guarded"})
    tag_id = created.json()["id"]

    assert (await viewer_client.post(TAGS, json={"name": "Other"})).status_code == 403
    renamed = await viewer_client.put(f"{TAGS}/{tag_id}", json={"name": "Hijacked"})
    assert renamed.status_code == 403
    assert (await viewer_client.delete(f"{TAGS}/{tag_id}")).status_code == 403
