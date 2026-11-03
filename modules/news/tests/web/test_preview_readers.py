"""Reading an article the way readers will, before they can.

The workflow's gap: ``approve`` publishes in one action, so a reviewer who has
only ever seen the block canvas — an editor, with drag handles and editor
chrome — commits an article to readers without having looked at it. The public
viewer cannot answer instead and must not be taught to: it serves published rows
only, and every other row 404s identically so that nothing leaks. So there is a
second route, behind ``news.edit``, that renders the *same screen* over
``draft_data``.

Two things it must not become, and both are asserted below: a way for anyone
without ``news.edit`` to learn that an article exists, and a page a crawler will
index. The last class holds the regression that would matter most — that the
public viewer still 404s a draft exactly as it did.
"""

from __future__ import annotations

import pytest
from news.core.constants import NOINDEX_ROBOTS_TAG, PRIVATE_CACHE_CONTROL
from news.models import ArticleStatus

from tests.support.preview import body_with, edit_body, page_props, preview_of, seed

pytestmark = pytest.mark.asyncio

NEWS = "/news"



class TestItIsNotForReaders:
    async def test_the_head_says_noindex(self, editor_client) -> None:
        """Permission-gated already, but a preview URL gets pasted into a chat
        and a crawler should refuse it on its own."""
        article = await seed(editor_client, "unlisted", status=ArticleStatus.DRAFT)

        body = (await editor_client.get(preview_of(article.id))).text

        assert '<meta name="robots" content="noindex,nofollow">' in body

    async def test_it_says_noindex_in_a_header_too(self, editor_client) -> None:
        """The head is written into the document, and ``_head.inject`` has
        nowhere to write on an Inertia XHR. The header has no such gap."""
        article = await seed(editor_client, "unlisted", status=ArticleStatus.DRAFT)

        response = await editor_client.get(preview_of(article.id))

        assert response.headers["X-Robots-Tag"] == NOINDEX_ROBOTS_TAG

    async def test_it_is_never_stored(self, editor_client) -> None:
        article = await seed(editor_client, "unlisted", status=ArticleStatus.DRAFT)

        response = await editor_client.get(preview_of(article.id))

        assert response.headers["Cache-Control"] == PRIVATE_CACHE_CONTROL

    async def test_it_claims_to_be_canonical_for_nothing(self, editor_client) -> None:
        """A permission-gated address is not the canonical version of anything,
        and the public URL it could name may not resolve at all."""
        article = await seed(editor_client, "unlisted", status=ArticleStatus.DRAFT)

        body = (await editor_client.get(preview_of(article.id))).text

        assert '<link rel="canonical"' not in body

    async def test_the_public_viewer_still_404s_a_draft(self, anon_client) -> None:
        """The regression that would matter most: nothing about the preview may
        soften the rule that an unpublished article is not on the public site."""
        await seed(anon_client, "unfinished", status=ArticleStatus.DRAFT)

        assert (await anon_client.get(f"{NEWS}/unfinished")).status_code == 404

    async def test_the_public_viewer_still_serves_the_snapshot(
        self, editor_public_client
    ) -> None:
        """And the other half of it: the viewer reads ``published_data``, so an
        edited draft changes nothing about what readers get."""
        article = await seed(
            editor_public_client, "steady", draft_data=body_with("as-published")
        )
        await edit_body(editor_public_client, article.id, body_with("draft-only"))

        assert "draft-only" not in (
            await editor_public_client.get(f"{NEWS}/steady")
        ).text


class TestLanguage:
    async def test_it_renders_the_article_in_its_own_language(
        self, bilingual, editor_client
    ) -> None:
        """Addressed by id rather than by ``(locale, slug)``, so unlike the
        public viewer there is no second router the article could be reached
        through and no way to ask for one language's article under another's
        prefix — the row's own ``locale`` is the only answer there is."""
        article = await seed(editor_client, "haushalt", locale="de")

        response = await editor_client.get(preview_of(article.id))

        assert response.headers["Content-Language"] == "de"
        assert page_props(response.text)["locale"] == "de"
        assert '<meta property="og:locale" content="de">' in response.text

    async def test_the_live_link_carries_the_language_prefix(
        self, bilingual, editor_client
    ) -> None:
        article = await seed(editor_client, "haushalt", locale="de")

        preview = page_props((await editor_client.get(preview_of(article.id))).text)[
            "preview"
        ]

        assert preview["live_url"] == "/de/news/haushalt"
