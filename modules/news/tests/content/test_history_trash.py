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
from news.models import ArticleStatus, RevisionEvent

from tests.support.factories import make_article
from tests.support.workflow import _draft

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"



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

    async def test_purging_a_live_article_is_refused(self, editor_client) -> None:
        """Purge is the Trash screen's "delete forever": a live article has to
        be trashed first, so there is always a step at which it can come back."""
        article = await _draft(editor_client, slug="still-here")

        refused = await editor_client.delete(f"{ARTICLES}/{article.id}/purge")
        assert refused.status_code == 409
        assert (await editor_client.get(ARTICLES)).json()["total"] == 1

        await editor_client.post(f"{ARTICLES}/{article.id}/trash")
        purged = await editor_client.delete(f"{ARTICLES}/{article.id}/purge")
        assert purged.status_code == 204
