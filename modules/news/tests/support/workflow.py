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

from news.models import ArticleStatus

from tests.support.factories import make_article


async def _draft(client, slug="a-draft"):
    async with client.db_state.session_factory() as db:
        return await make_article(
            db, slug=slug, title="A draft", status=ArticleStatus.DRAFT
        )
