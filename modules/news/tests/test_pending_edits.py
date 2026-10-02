"""What the admin list says about a live article whose author kept writing.

Publishing snapshots ``draft_data`` into ``published_data``, and the author
carries on. From that moment the row is two documents: the one readers are
served and the one on screen. The list badge said "Published" about the second
while describing the first — truthfully, and about the wrong document, with
nothing to say the two had parted company.

The preview screen already knew — see ``endpoints.views._preview_state`` — and
the subtlety it encodes is the one a naive listing gets wrong: the flag is
anded with the article being *genuinely live*. A draft can hold a snapshot from
before it was taken down, and "readers are still seeing the published version"
is simply false there. The last class pins the two answers to each other, in
both directions, because they are computed in different languages — one in
Python over an entity, one in SQL over a page of rows — and nothing but a test
keeps them saying the same thing.
"""

from __future__ import annotations

import json
import re

import pytest
from factories import make_article
from news.constants import ROUTE_PREFIX_API
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"
FLAG = "has_unpublished_changes"


def body_with(marker: str) -> dict:
    return {
        "root": {"props": {"title": marker}},
        "content": [{"type": "Text", "props": {"id": "t", "text": marker}}],
    }


async def seed(client, slug: str, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, title=slug, **kwargs)


async def edit_body(client, article_id: int, data: dict) -> None:
    """The canvas autosave: the draft only, never the live copy."""
    async with client.db_state.session_factory() as db:
        await ArticlesService(db).save_body(article_id, data)
        await db.commit()


async def trash(client, article_id: int) -> None:
    async with client.db_state.session_factory() as db:
        await ArticlesService(db).trash(article_id)
        await db.commit()


async def unpublish(client, article_id: int) -> None:
    async with client.db_state.session_factory() as db:
        await ArticlesService(db).unpublish(article_id)
        await db.commit()


async def flag_for(client, slug: str) -> bool:
    """The listing's answer for one article."""
    response = await client.get(ARTICLES, params={"limit": 50})
    assert response.status_code == 200, response.text
    rows = {item["slug"]: item for item in response.json()["items"]}
    assert slug in rows, rows.keys()
    return rows[slug][FLAG]


class TestTheListingFlagsADivergedDraft:
    async def test_a_published_article_whose_draft_moved_on_is_flagged(
        self, editor_client
    ) -> None:
        article = await seed(editor_client, "moving", draft_data=body_with("v1"))
        await edit_body(editor_client, article.id, body_with("v2"))

        assert await flag_for(editor_client, "moving") is True

    async def test_an_untouched_published_article_is_not(self, editor_client) -> None:
        await seed(editor_client, "settled", draft_data=body_with("v1"))

        assert await flag_for(editor_client, "settled") is False

    async def test_an_autosave_that_changed_nothing_is_not(
        self, editor_client
    ) -> None:
        """A content comparison, not a timestamp one. The canvas saves on a
        timer, so a row can be written without the document changing — and an
        editor told there are unpublished edits every time they open an article
        stops reading the badge."""
        article = await seed(editor_client, "resaved", draft_data=body_with("v1"))
        await edit_body(editor_client, article.id, body_with("v1"))

        assert await flag_for(editor_client, "resaved") is False

    async def test_a_draft_holding_an_old_snapshot_is_not_flagged(
        self, editor_client
    ) -> None:
        """The case the preview screen got right and a naive implementation
        gets wrong. This article was published, edited, and then taken down: it
        still carries the snapshot readers used to get, and its draft still
        differs from it. But nothing is live, so "readers are still being
        served the published version" is a sentence about nobody."""
        article = await seed(editor_client, "withdrawn", draft_data=body_with("v1"))
        await edit_body(editor_client, article.id, body_with("v2"))
        await unpublish(editor_client, article.id)

        assert await flag_for(editor_client, "withdrawn") is False

    async def test_a_binned_article_is_not_flagged_in_the_trash(
        self, editor_client
    ) -> None:
        """Trashing keeps the status and the snapshot, and the viewer 404s the
        article regardless — so the one listing that shows binned rows must not
        say readers are still being served something."""
        article = await seed(editor_client, "binned", draft_data=body_with("v1"))
        await edit_body(editor_client, article.id, body_with("v2"))
        await trash(editor_client, article.id)

        response = await editor_client.get(ARTICLES, params={"trashed": "true"})
        rows = {item["slug"]: item for item in response.json()["items"]}

        assert rows["binned"][FLAG] is False

    async def test_a_draft_that_was_never_published_is_not_flagged(
        self, editor_client
    ) -> None:
        await seed(
            editor_client,
            "unfinished",
            status=ArticleStatus.DRAFT,
            publish_body=False,
            draft_data=body_with("v1"),
        )

        assert await flag_for(editor_client, "unfinished") is False

    async def test_the_single_article_read_agrees_with_the_listing(
        self, editor_client
    ) -> None:
        """``get_read`` shares the listing's query so the row a just-saved
        article is read back through cannot describe it differently."""
        article = await seed(editor_client, "written", draft_data=body_with("v1"))
        await edit_body(editor_client, article.id, body_with("v2"))

        detail = await editor_client.get(f"{ARTICLES}/{article.id}/detail")

        assert detail.status_code == 200, detail.text
        assert detail.json()[FLAG] is True


class TestAnonymousCardsDoNotCarryIt:
    """Editorial work in progress is not part of the public listing.

    The same rule that makes ``status`` always ``published`` for a caller
    without ``news.edit``: an anonymous reader has no business learning that an
    update to a story is being written. The column is not even selected for
    them, so the answer is the field's default rather than a suppressed value.
    """

    async def test_a_reader_never_sees_the_flag_set(self, anon_client) -> None:
        article = await seed(anon_client, "moving", draft_data=body_with("v1"))
        await edit_body(anon_client, article.id, body_with("v2"))

        response = await anon_client.get(ARTICLES)

        assert [item["slug"] for item in response.json()["items"]] == ["moving"]
        assert [item[FLAG] for item in response.json()["items"]] == [False]


class TestTheListAndThePreviewAgree:
    """Two implementations of one rule — SQL for a page of rows, Python for the
    entity the preview holds. They can only be kept in step by a test that asks
    both about the same article."""

    def _preview_flag(self, rendered: str) -> bool:
        match = re.search(r"data-page='(.*?)'></div>", rendered, re.S)
        assert match is not None, rendered[:500]
        return json.loads(match.group(1))["props"]["preview"][FLAG]

    async def _both(self, client, slug: str, article_id: int) -> tuple[bool, bool]:
        preview = await client.get(f"/admin/news/articles/{article_id}/preview")
        assert preview.status_code == 200, preview.text
        return await flag_for(client, slug), self._preview_flag(preview.text)

    async def test_they_agree_that_a_live_article_has_diverged(
        self, editor_client
    ) -> None:
        article = await seed(editor_client, "moving", draft_data=body_with("v1"))
        await edit_body(editor_client, article.id, body_with("v2"))

        assert await self._both(editor_client, "moving", article.id) == (True, True)

    async def test_they_agree_that_a_withdrawn_one_has_not(
        self, editor_client
    ) -> None:
        article = await seed(editor_client, "withdrawn", draft_data=body_with("v1"))
        await edit_body(editor_client, article.id, body_with("v2"))
        await unpublish(editor_client, article.id)

        assert await self._both(editor_client, "withdrawn", article.id) == (
            False,
            False,
        )
