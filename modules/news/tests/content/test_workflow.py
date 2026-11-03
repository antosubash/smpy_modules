"""The article workflow, and who is allowed to move it.

This file replaces ``test_page_write_permissions.py``, which asked a question
that no longer has a subject: "news writes a page on the author's behalf — under
whose authority?" It answered *pagebuilder's*, because creating and publishing
an article wrote one of its pages, and news was not entitled to route an author
past a separation that module maintained.

News owns the document now, so it owns the separation. ``news.publish`` is the
gate, and these are the cases that used to be spelled with
``pagebuilder.publish``. The point is unchanged: an author who may write must not
thereby be able to put something in front of readers.
"""

from __future__ import annotations

import pytest
from news.content.articles import ArticlesService
from news.core.constants import ROUTE_PREFIX_API
from news.models import ArticleStatus

from tests.support.factories import make_article
from tests.support.workflow import _draft

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"



class TestPublishSeparation:
    """``news.edit`` is not enough to reach readers."""

    async def test_publishing_needs_news_publish(self, author_client) -> None:
        article = await _draft(author_client)

        response = await author_client.post(f"{ARTICLES}/{article.id}/publish")

        assert response.status_code in (401, 403)

    async def test_unpublishing_needs_news_publish(self, author_client) -> None:
        article = await _draft(author_client)

        response = await author_client.post(f"{ARTICLES}/{article.id}/unpublish")

        assert response.status_code in (401, 403)

    async def test_purging_needs_news_publish(self, author_client) -> None:
        """The one action in the module that cannot be undone."""
        article = await _draft(author_client)

        response = await author_client.delete(f"{ARTICLES}/{article.id}/purge")

        assert response.status_code in (401, 403)

    async def test_deleting_outright_needs_news_publish(self, author_client) -> None:
        """The same act as ``purge``, reached by a different route.

        ``DELETE /articles/{id}`` removes the row and its body for good — no
        trash, nothing to restore — so gating it on ``news.edit`` alone left the
        separation with a door straight through it: an author who could not
        purge a *trashed* article could hard-delete a live one.
        """
        article = await _draft(author_client)

        response = await author_client.delete(f"{ARTICLES}/{article.id}")

        assert response.status_code in (401, 403)

    async def test_trashing_still_needs_only_news_edit(self, author_client) -> None:
        """The recoverable door the tightening above leaves an author open."""
        article = await _draft(author_client, slug="binnable")

        response = await author_client.post(f"{ARTICLES}/{article.id}/trash")

        assert response.status_code == 204, response.text

    async def test_writing_still_needs_only_news_edit(self, author_client) -> None:
        """The gate is on reaching readers, not on writing.

        Requiring ``news.publish`` to create or edit would make the module
        unusable for exactly the role the separation exists to serve.
        """
        response = await author_client.post(ARTICLES, json={"title": "Mine"})

        assert response.status_code == 201

    async def test_submitting_for_review_still_needs_only_news_edit(
        self, author_client
    ) -> None:
        """Gating this on ``news.publish`` would close the only door the
        separation leaves an author."""
        article = await _draft(author_client)

        response = await author_client.post(f"{ARTICLES}/{article.id}/submit")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == ArticleStatus.SUBMITTED_FOR_REVIEW.value

    async def test_an_editor_with_publish_can_publish(self, editor_client) -> None:
        article = await _draft(editor_client)

        response = await editor_client.post(f"{ARTICLES}/{article.id}/publish")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == ArticleStatus.PUBLISHED.value

    async def test_a_missing_article_is_a_404(self, editor_client) -> None:
        assert (await editor_client.post(f"{ARTICLES}/999/publish")).status_code == 404


class TestDraftAndPublishedAreSeparate:
    async def test_publishing_snapshots_the_draft(self, db) -> None:
        article = await make_article(
            db, slug="snap", status=ArticleStatus.DRAFT, publish_body=False,
            draft_data={"content": [{"type": "Text", "props": {"text": "v1"}}]},
        )

        await ArticlesService(db).publish(article.id)

        assert article.published_data == article.draft_data

    async def test_editing_after_publish_does_not_reach_readers(self, db) -> None:
        """The whole reason there are two columns.

        An author fixing a typo on a live article is not republishing it.
        """
        article = await make_article(
            db, slug="live", status=ArticleStatus.DRAFT, publish_body=False,
            draft_data={"content": [{"type": "Text", "props": {"text": "v1"}}]},
        )
        service = ArticlesService(db)
        await service.publish(article.id)

        await service.save_body(
            article.id, {"content": [{"type": "Text", "props": {"text": "v2"}}]}
        )

        assert article.published_data["content"][0]["props"]["text"] == "v1"
        assert article.draft_data["content"][0]["props"]["text"] == "v2"

    async def test_unpublishing_keeps_what_readers_last_saw(self, db) -> None:
        """Discarding it would make "what was live before I pulled it?"
        unanswerable."""
        article = await make_article(db, slug="pulled", status=ArticleStatus.DRAFT,
                                     publish_body=False)
        service = ArticlesService(db)
        await service.publish(article.id)

        await service.unpublish(article.id)

        assert article.status is ArticleStatus.DRAFT
        assert article.published_data is not None


class TestReview:
    async def test_approving_publishes(self, db) -> None:
        """One action, because approving a submission the reviewer then has to
        publish separately is a step that only ever gets forgotten."""
        article = await make_article(db, slug="queued", status=ArticleStatus.DRAFT,
                                     publish_body=False)
        service = ArticlesService(db)
        await service.submit_for_review(article.id)

        await service.approve(article.id)

        assert article.status is ArticleStatus.PUBLISHED
        assert article.published_data is not None

    async def test_rejecting_returns_it_to_draft_with_a_reason(self, db) -> None:
        article = await make_article(db, slug="sent-back", status=ArticleStatus.DRAFT,
                                     publish_body=False)
        service = ArticlesService(db)
        await service.submit_for_review(article.id)

        await service.reject(article.id, "Needs a source for the second claim.")

        assert article.status is ArticleStatus.DRAFT
        assert article.rejection_note == "Needs a source for the second claim."

    async def test_resubmitting_clears_the_stale_rejection_note(self, db) -> None:
        """Otherwise the banner from the last round shadows the new one."""
        article = await make_article(db, slug="round-two", status=ArticleStatus.DRAFT,
                                     publish_body=False)
        service = ArticlesService(db)
        await service.submit_for_review(article.id)
        await service.reject(article.id, "First pass")

        await service.submit_for_review(article.id)

        assert article.rejection_note is None

    async def test_only_a_submitted_article_can_be_approved(self, db) -> None:
        article = await make_article(db, slug="not-queued", status=ArticleStatus.DRAFT,
                                     publish_body=False)

        with pytest.raises(Exception) as exc:
            await ArticlesService(db).approve(article.id)

        assert getattr(exc.value, "status_code", None) == 409
