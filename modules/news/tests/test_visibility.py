"""Who sees what, over HTTP.

Split out of ``test_api.py`` when that file outgrew the repo's 300-line cap.
They belong together anyway: both classes are about the same question — the
listing is anonymously readable, so every rule that keeps unpublished work off
the public site has to hold at the endpoint rather than in a screen.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news.constants import ROUTE_PREFIX_API
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"
CATEGORIES = f"{ROUTE_PREFIX_API}/categories"


async def _seed(client, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, **kwargs)


class TestDraftVisibility:
    """Regression: `may_see_drafts` read `user.permissions`, which UserContext
    does not have, so it was always False and no editor ever saw a draft."""

    async def _draft_article(self, client) -> None:
        await _seed(
            client,
            slug="wip",
            title="Work in progress",
            status=ArticleStatus.DRAFT,
            category="News",
        )

    async def test_an_editor_sees_a_draft(self, editor_client) -> None:
        await self._draft_article(editor_client)

        body = (await editor_client.get(ARTICLES)).json()

        assert body["total"] == 1
        assert body["items"][0]["title"] == "Work in progress"
        # And the listing says *that* it is a draft — the admin list badges
        # rows with this rather than making a second request per page.
        assert body["items"][0]["status"] == "draft"

    async def test_an_admin_sees_a_draft(self, admin_client) -> None:
        # An admin resolves to WILDCARD rather than to a literal `news.edit`,
        # so a plain membership test against the resolved set would miss them.
        await self._draft_article(admin_client)

        assert (await admin_client.get(ARTICLES)).json()["total"] == 1

    async def test_an_anonymous_visitor_does_not(self, anon_client) -> None:
        # The whole point of the published/draft split: the public feed block
        # runs with no session and must show the published site only.
        await self._draft_article(anon_client)

        assert (await anon_client.get(ARTICLES)).json()["total"] == 0

    async def test_a_viewer_without_edit_does_not(self, viewer_client) -> None:
        await self._draft_article(viewer_client)

        assert (await viewer_client.get(ARTICLES)).json()["total"] == 0

    async def test_a_published_article_is_visible_to_everyone(
        self, anon_client
    ) -> None:
        await _seed(anon_client, slug="live", title="Live", category="News")

        body = (await anon_client.get(ARTICLES)).json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "published"

    async def test_categories_follow_the_same_rule(self, anon_client) -> None:
        await self._draft_article(anon_client)

        assert (await anon_client.get(CATEGORIES)).json()["items"] == []

    async def test_a_trashed_article_is_hidden_from_the_editor_too(
        self, editor_client
    ) -> None:
        article = await _seed(editor_client, slug="binned", title="Binned")

        await editor_client.post(f"{ARTICLES}/{article.id}/trash")

        assert (await editor_client.get(ARTICLES)).json()["total"] == 0


class TestWritesRequirePermission:
    async def test_anonymous_cannot_create(self, anon_client) -> None:
        response = await anon_client.post(ARTICLES, json={"title": "x"})
        assert response.status_code == 401

    async def test_a_viewer_cannot_create(self, viewer_client) -> None:
        response = await viewer_client.post(ARTICLES, json={"title": "x"})
        assert response.status_code == 403

    async def test_a_viewer_cannot_delete(self, viewer_client) -> None:
        response = await viewer_client.delete(f"{ARTICLES}/1")
        assert response.status_code == 403
