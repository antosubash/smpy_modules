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
from conftest import make_article
from news.constants import ROUTE_PREFIX_API
from news.content import ArticlesService
from news.models import ArticleStatus, RevisionEvent

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _draft(client, slug="a-draft"):
    async with client.db_state.session_factory() as db:
        return await make_article(
            db, slug=slug, title="A draft", status=ArticleStatus.DRAFT
        )


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


class TestRevisions:
    async def test_every_transition_records_one(self, db) -> None:
        """The history is the audit log rather than something kept beside it."""
        article = await make_article(db, slug="tracked", status=ArticleStatus.DRAFT,
                                     publish_body=False)
        service = ArticlesService(db)

        await service.publish(article.id)
        await service.unpublish(article.id)

        events = [r.event for r in await service.list_revisions(article.id)]
        assert events == [RevisionEvent.UNPUBLISH, RevisionEvent.PUBLISH]

    async def test_restoring_a_revision_does_not_publish_it(self, db) -> None:
        """Restoring is an editing action — the author looks at what came back
        before deciding it should be live."""
        article = await make_article(db, slug="restored", status=ArticleStatus.DRAFT,
                                     publish_body=False,
                                     draft_data={"content": ["v1"]})
        service = ArticlesService(db)
        await service.publish(article.id)
        await service.save_body(article.id, {"content": ["v2"]})
        revision = (await service.list_revisions(article.id))[0]

        await service.restore_revision(article.id, revision.id)

        assert article.draft_data == {"content": ["v1"]}
        assert article.published_data == {"content": ["v1"]}
        # Still published from before — restore did not republish, it just put
        # the old draft back.
        assert article.status is ArticleStatus.PUBLISHED

    async def test_a_revision_of_another_article_is_a_404(self, db) -> None:
        mine = await make_article(db, slug="mine", status=ArticleStatus.DRAFT,
                                  publish_body=False)
        theirs = await make_article(db, slug="theirs", status=ArticleStatus.DRAFT,
                                    publish_body=False)
        service = ArticlesService(db)
        await service.publish(theirs.id)
        stolen = (await service.list_revisions(theirs.id))[0]

        with pytest.raises(Exception) as exc:
            await service.get_revision(mine.id, stolen.id)

        assert getattr(exc.value, "status_code", None) == 404


class TestTrash:
    async def test_trashing_hides_it_and_restoring_brings_it_back(
        self, editor_client
    ) -> None:
        article = await _draft(editor_client, slug="temp")

        assert (await editor_client.post(f"{ARTICLES}/{article.id}/trash")).status_code == 204
        assert (await editor_client.get(ARTICLES)).json()["total"] == 0

        assert (await editor_client.post(f"{ARTICLES}/{article.id}/restore")).status_code == 200
        assert (await editor_client.get(ARTICLES)).json()["total"] == 1

    async def test_restore_leaves_the_status_alone(self, db) -> None:
        """An article that was published when it was binned is published again —
        the only reading of "restore" that does not quietly change what readers
        can see."""
        article = await make_article(db, slug="was-live")
        service = ArticlesService(db)
        await service.trash(article.id)

        await service.restore(article.id)

        assert article.status is ArticleStatus.PUBLISHED
