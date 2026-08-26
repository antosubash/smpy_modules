"""Listing the trash — the complement of the filter every other listing applies.

Trash, restore and purge were implemented and tested from the day this module
owned its own content, and there was no way to *see* what was in the bin. So the
admin list offered a hard delete instead, which is the one action a soft delete
exists to avoid, and a trashed article was reachable only over the API.

That matters beyond recovery: a trashed article keeps its slug claimed, so an
author who bins one and cannot find it tries to recreate it and is told the URL
is taken by something they cannot see.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news.constants import ROUTE_PREFIX_API
from news.content import ArticlesService

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _binned(client, slug: str) -> int:
    async with client.db_state.session_factory() as db:
        article = await make_article(db, slug=slug, title=slug)
        await ArticlesService(db).trash(article.id)
        await db.commit()
        return article.id


class TestTrashListing:
    async def test_it_lists_what_the_ordinary_list_hides(self, editor_client) -> None:
        await _binned(editor_client, "binned")
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="kept", title="kept")

        trash = (await editor_client.get(f"{ARTICLES}?trashed=true")).json()
        listing = (await editor_client.get(ARTICLES)).json()

        assert [i["slug"] for i in trash["items"]] == ["binned"]
        assert [i["slug"] for i in listing["items"]] == ["kept"]

    async def test_restoring_moves_it_back(self, editor_client) -> None:
        article_id = await _binned(editor_client, "recovered")

        restored = await editor_client.post(f"{ARTICLES}/{article_id}/restore")
        assert restored.status_code == 200, restored.text

        trash = (await editor_client.get(f"{ARTICLES}?trashed=true")).json()
        listing = (await editor_client.get(ARTICLES)).json()
        assert trash["items"] == []
        assert [i["slug"] for i in listing["items"]] == ["recovered"]

    async def test_an_empty_trash_is_an_empty_list(self, editor_client) -> None:
        assert (await editor_client.get(f"{ARTICLES}?trashed=true")).json()["items"] == []

    async def test_an_anonymous_reader_gets_nothing_from_it(self, anon_client) -> None:
        # Not a 403: the flag is simply ignored for a caller who cannot see
        # drafts, and a trashed article is by definition not published. Asking
        # for the bin without the right to see it returns the empty set rather
        # than confirming there is one.
        await _binned(anon_client, "secret")

        body = (await anon_client.get(f"{ARTICLES}?trashed=true")).json()

        assert body["items"] == []

    async def test_a_viewer_without_edit_gets_nothing_either(self, viewer_client) -> None:
        await _binned(viewer_client, "also-secret")

        body = (await viewer_client.get(f"{ARTICLES}?trashed=true")).json()

        assert body["items"] == []


class TestTagFilter:
    async def test_it_narrows_to_articles_carrying_the_tag(self, editor_client) -> None:
        from news.models import NewsArticleTag, NewsTag

        async with editor_client.db_state.session_factory() as db:
            tagged = await make_article(db, slug="tagged", title="tagged")
            await make_article(db, slug="plain", title="plain")
            tag = NewsTag(name="Canopy", slug="canopy")
            db.add(tag)
            await db.flush()
            db.add(NewsArticleTag(article_id=tagged.id, tag_id=tag.id))
            await db.commit()

        by_slug = (await editor_client.get(f"{ARTICLES}?tag=canopy")).json()
        by_name = (await editor_client.get(f"{ARTICLES}?tag=Canopy")).json()

        assert [i["slug"] for i in by_slug["items"]] == ["tagged"]
        assert [i["slug"] for i in by_name["items"]] == ["tagged"]

    async def test_an_unknown_tag_matches_nothing_rather_than_everything(
        self, editor_client
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="anything", title="anything")

        body = (await editor_client.get(f"{ARTICLES}?tag=nope")).json()

        assert body["items"] == []
