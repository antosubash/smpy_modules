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

import json
import re

import pytest
from factories import make_article
from news.constants import NOINDEX_ROBOTS_TAG, PRIVATE_CACHE_CONTROL
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

NEWS = "/news"


def preview_of(article_id: int) -> str:
    """Spelled out rather than formatted from the constant the route uses: a
    test that built the address the same way the code does would keep passing
    if both moved together."""
    return f"/admin/news/articles/{article_id}/preview"


def body_with(marker: str) -> dict:
    """A block document carrying one findable string."""
    return {
        "root": {"props": {"title": marker}},
        "content": [{"type": "Text", "props": {"id": "t", "text": marker}}],
        "zones": {},
    }


def page_props(rendered: str) -> dict:
    """The Inertia props out of the rendered shell.

    The attribute holds the page JSON with ``<``, ``>``, ``&`` and the quote
    written as unicode escapes, which are ordinary JSON and need no unescaping
    of their own.
    """
    match = re.search(r"data-page='(.*?)'></div>", rendered, re.S)
    assert match is not None, rendered[:500]
    return json.loads(match.group(1))["props"]


async def seed(client, slug: str, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, title=slug, **kwargs)


async def edit_body(client, article_id: int, data: dict) -> None:
    """Autosave over the draft, leaving any published snapshot alone — which is
    exactly how an author's draft comes to differ from what readers have."""
    async with client.db_state.session_factory() as db:
        await ArticlesService(db).save_body(article_id, data)
        await db.commit()


class TestWhoMaySee:
    async def test_a_reviewer_sees_a_submitted_article(self, editor_client) -> None:
        """The case the feature exists for: approving publishes in the same
        action, so the reviewer has to be able to read it first."""
        article = await seed(
            editor_client,
            "awaiting",
            status=ArticleStatus.SUBMITTED_FOR_REVIEW,
            publish_body=False,
            draft_data=body_with("submitted-for-review-copy"),
        )

        response = await editor_client.get(preview_of(article.id))

        assert response.status_code == 200, response.text
        assert "submitted-for-review-copy" in response.text

    async def test_an_author_sees_their_own_draft(self, author_client) -> None:
        """``news.edit`` alone. Gating on ``news.publish`` would put the preview
        behind the very permission the reviewer is deciding whether to use."""
        article = await seed(
            author_client,
            "unfinished",
            status=ArticleStatus.DRAFT,
            publish_body=False,
            draft_data=body_with("still-being-written"),
        )

        response = await author_client.get(preview_of(article.id))

        assert response.status_code == 200, response.text
        assert "still-being-written" in response.text

    async def test_an_anonymous_caller_gets_a_404(self, anon_client) -> None:
        """Not a 401 and not a 403 — either would confirm the article exists to
        anyone who can guess an id, which is what the viewer's uniform 404 is
        there to refuse."""
        article = await seed(anon_client, "secret", status=ArticleStatus.DRAFT)

        assert (await anon_client.get(preview_of(article.id))).status_code == 404

    async def test_a_viewer_without_edit_gets_the_same_404(self, viewer_client) -> None:
        article = await seed(viewer_client, "secret", status=ArticleStatus.DRAFT)

        assert (await viewer_client.get(preview_of(article.id))).status_code == 404

    async def test_an_article_that_never_existed_answers_the_same(
        self, editor_client
    ) -> None:
        assert (await editor_client.get(preview_of(9999))).status_code == 404

    async def test_a_trashed_article_is_a_404(self, editor_client) -> None:
        """The public viewer 404s a binned article the moment it is binned; the
        preview is not a way around that."""
        article = await seed(editor_client, "binned")
        async with editor_client.db_state.session_factory() as db:
            await ArticlesService(db).trash(article.id)
            await db.commit()

        assert (await editor_client.get(preview_of(article.id))).status_code == 404


class TestWhatItShows:
    async def test_it_serves_the_draft_while_the_public_url_serves_the_published(
        self, editor_public_client
    ) -> None:
        """The second gap: an author keeps working after publishing, and until
        now there was no way to see the pending version at all."""
        article = await seed(
            editor_public_client, "revised", draft_data=body_with("as-published")
        )
        await edit_body(editor_public_client, article.id, body_with("rewritten-since"))

        preview = await editor_public_client.get(preview_of(article.id))
        live = await editor_public_client.get(f"{NEWS}/revised")

        assert "rewritten-since" in preview.text
        assert "as-published" in live.text
        assert "rewritten-since" not in live.text

    async def test_it_says_there_are_unpublished_changes(
        self, editor_public_client
    ) -> None:
        article = await seed(
            editor_public_client, "diverged", draft_data=body_with("as-published")
        )
        await edit_body(editor_public_client, article.id, body_with("newer"))

        preview = page_props(
            (await editor_public_client.get(preview_of(article.id))).text
        )["preview"]

        assert preview["has_unpublished_changes"] is True
        assert preview["live_url"] == f"{NEWS}/diverged"

    async def test_an_untouched_published_article_reports_no_changes(
        self, editor_client
    ) -> None:
        article = await seed(editor_client, "unchanged")

        preview = page_props((await editor_client.get(preview_of(article.id))).text)[
            "preview"
        ]

        assert preview["has_unpublished_changes"] is False
        assert preview["status"] == "published"

    async def test_a_draft_offers_no_live_link(self, editor_client) -> None:
        """There is nothing at the public URL, so a "view live" link would be a
        link to a 404."""
        article = await seed(
            editor_client, "never-live", status=ArticleStatus.DRAFT, publish_body=False
        )

        preview = page_props((await editor_client.get(preview_of(article.id))).text)[
            "preview"
        ]

        assert preview["live_url"] is None
        assert preview["status"] == "draft"

    async def test_the_public_page_carries_no_preview_prop(self, anon_client) -> None:
        """Absent entirely rather than sent as null: this prop is what makes the
        banner appear, and a reader's page should not carry even an empty one."""
        await seed(anon_client, "ordinary")

        assert "preview" not in page_props((await anon_client.get(f"{NEWS}/ordinary")).text)


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
