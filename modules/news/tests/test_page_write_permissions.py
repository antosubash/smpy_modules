"""News writes a page on the author's behalf — under whose authority.

Creating and publishing an article used to happen in the browser, against
pagebuilder's own endpoints, so both met that module's permission gate. Moving
them server-side had to keep meeting it: pagebuilder separates editor from
publisher deliberately, and news is not entitled to route an article author
past a separation the host set up.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import service
from news.constants import ROUTE_PREFIX_API
from news.integrations.pagebuilder import Page
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

WITH_PAGE = f"{ROUTE_PREFIX_API}/articles/with-page"
ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _count(client, model) -> int:
    async with client.db_state.session_factory() as db:
        return int(await db.scalar(select(func.count()).select_from(model)) or 0)


class TestPageWritesKeepPagebuildersPermissions:
    """Moving these writes server-side must not move them past pagebuilder's
    own gate.

    That module separates editor from publisher deliberately — its ``_deps``
    says so: "let hosts run the editor → publisher workflow without granting
    every editor publish rights." The browser path these routes replaced went
    through pagebuilder's endpoints and met that gate. Requiring only
    ``news.edit`` here would have handed every article author a way straight
    past it: create pages without ``pagebuilder.edit``, publish without
    ``pagebuilder.publish``.
    """

    async def test_creating_a_page_needs_pagebuilders_edit(
        self, news_only_client
    ) -> None:
        response = await news_only_client.post(WITH_PAGE, json={"title": "Estonia"})

        assert response.status_code in (401, 403)
        assert await _count(news_only_client, Page) == 0

    async def test_publishing_needs_pagebuilders_publish(
        self, news_only_client, editor_client
    ) -> None:
        async with news_only_client.db_state.session_factory() as db:
            page = await make_page(db, slug="a-draft", title="A draft")
            article = await service.create(
                db, page_id=page.id, category="", published_at=None
            )
            await db.commit()
            article_id = article.id

        response = await news_only_client.post(
            f"{ARTICLES}/{article_id}/publish", json={}
        )

        assert response.status_code in (401, 403)

    async def test_attaching_metadata_still_needs_only_news_edit(
        self, news_only_client
    ) -> None:
        """The gate is on the *page* writes, not on news' own.

        Attaching metadata to a page somebody else already made touches nothing
        of pagebuilder's, so requiring its permission here would make the module
        unusable for exactly the role it exists to serve.
        """
        async with news_only_client.db_state.session_factory() as db:
            page = await make_page(db, slug="existing", title="Existing")
            await db.commit()
            page_id = page.id

        response = await news_only_client.post(
            ARTICLES, json={"page_id": page_id, "category": "", "published_at": None}
        )

        assert response.status_code == 201
