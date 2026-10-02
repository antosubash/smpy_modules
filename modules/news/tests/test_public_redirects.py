"""Renaming an article must not break the links already in the world.

Split from ``test_public_address`` for the repo's 300-line cap, at the seam
that was already there: that file is about where an article serves, this one is
about the addresses it used to serve at.

News used to read pagebuilder's redirect table, because the slug being renamed
was a page's. It keeps its own now — same rule, its own rows, and scoped to a
language, because slugs are only unique within one. The locale-scoping tests
live in ``test_locale_addressing``; what is here is the rule itself, which the
ship run's review sharpened and which must not soften in a merge.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import locales, redirects
from news.content import ArticlesService

pytestmark = pytest.mark.asyncio

NEWS = "/news"


async def _seed(client, slug: str, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, title=slug, **kwargs)


class TestRename:
    async def test_the_old_address_forwards_to_the_new_one(self, anon_client) -> None:
        article = await _seed(anon_client, "old-name")
        async with anon_client.db_state.session_factory() as db:
            await ArticlesService(db).update(article.id, {"slug": "new-name"})
            await db.commit()

        response = await anon_client.get(f"{NEWS}/old-name")

        assert response.status_code == 301
        assert response.headers["location"] == "/news/new-name"

    async def test_a_slug_nobody_renamed_forwards_nowhere(self, anon_client) -> None:
        await _seed(anon_client, "steady")

        assert (await anon_client.get(f"{NEWS}/never-used")).status_code == 404

    async def test_renaming_back_leaves_no_redirect_loop(self, db) -> None:
        """An article reclaiming an address it once redirected away would
        otherwise send readers straight back off it."""
        article = await make_article(db, slug="first")
        service = ArticlesService(db)
        await service.update(article.id, {"slug": "second"})

        await service.update(article.id, {"slug": "first"})

        assert await redirects.resolve(db, "first", locales.default()) is None


class TestItNeverForwardsToA404:
    """The ship run's fix, and the reason it is worth a class of its own.

    A redirect is a 301: a browser that followed one to a dead URL keeps doing
    so from cache long after the article comes back. So ``resolve`` refuses to
    hand back any target the public viewer would refuse to serve, and the
    conditions it applies are deliberately the viewer's own — not trashed,
    published, and carrying a snapshot.
    """

    async def test_it_does_not_forward_to_an_unpublished_article(
        self, anon_client
    ) -> None:
        """Published at A, renamed to B, then taken off the site."""
        article = await _seed(anon_client, "was-here")
        async with anon_client.db_state.session_factory() as db:
            service = ArticlesService(db)
            await service.update(article.id, {"slug": "now-here"})
            await service.unpublish(article.id)
            await db.commit()

        response = await anon_client.get(f"{NEWS}/was-here")

        assert response.status_code == 404, response.text

    async def test_it_does_not_forward_to_a_trashed_article(self, db) -> None:
        """The same refusal as the unpublished case, by the same shared rule.

        ``resolve`` open-coded ``deleted_at IS NULL`` where every other read
        path applies ``NOT_TRASHED``; this pins the behaviour so the one
        definition cannot quietly stop covering the redirect.
        """
        article = await make_article(db, slug="was-binned")
        service = ArticlesService(db)
        await service.update(article.id, {"slug": "now-binned"})
        await service.trash(article.id)

        assert await redirects.resolve(db, "was-binned", locales.default()) is None

    async def test_it_does_not_forward_to_an_article_with_no_snapshot(
        self, db
    ) -> None:
        """The check that has to stay in Python.

        ``published_data`` is a JSON column, and a Python ``None`` is stored in
        one as the JSON text ``null`` rather than as SQL NULL — so an
        ``IS NOT NULL`` in the ``WHERE`` is true of an unpublished snapshot too
        and would forward readers to a 404. This is the regression test for
        that, and it passes only while the check is done on the loaded row.
        """
        article = await make_article(db, slug="no-body", publish_body=False)
        await ArticlesService(db).update(article.id, {"slug": "still-no-body"})

        assert await redirects.resolve(db, "no-body", locales.default()) is None

    async def test_it_forwards_again_once_the_article_is_back(
        self, anon_client
    ) -> None:
        # Refusing while the article is down must not be permanent either: the
        # redirect row is still there, and republishing makes it good again.
        article = await _seed(anon_client, "returning")
        async with anon_client.db_state.session_factory() as db:
            service = ArticlesService(db)
            await service.update(article.id, {"slug": "returned"})
            await service.unpublish(article.id)
            await service.publish(article.id)
            await db.commit()

        response = await anon_client.get(f"{NEWS}/returning")

        assert response.status_code == 301
        assert response.headers["location"] == "/news/returned"
