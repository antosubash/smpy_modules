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

from news.content.articles import ArticlesService

from tests.support.factories import make_article


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
