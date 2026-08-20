"""The usage query matches an asset URL literally, wildcards and all.

``_`` is LIKE's single-character wildcard and it appears in almost every
uploaded filename. Unescaped, ``hero_1.png`` also matches ``heroX1.png`` — and
this query is what decides whether an asset is safe to delete, so a false match
refuses a deletion that should have been allowed and names a page that does not
actually use the file.
"""

from __future__ import annotations

import pytest
from pagebuilder import media_usage
from pagebuilder.models import Page

pytestmark = pytest.mark.asyncio


async def _page_using(db, url: str, *, title: str) -> Page:
    blocks = {"content": [{"type": "Image", "props": {"src": url}}]}
    page = Page(
        slug=title.lower().replace(" ", "-"),
        title=title,
        draft_data=blocks,
        published_data=None,
    )
    db.add(page)
    await db.flush()
    return page


async def test_underscore_is_not_a_wildcard(db) -> None:
    """The case that actually happens: an ordinary filename with an underscore."""
    await _page_using(db, "/media/pagebuilder/heroX1.png", title="Different asset")

    found, total = await media_usage.find(db, "/media/pagebuilder/hero_1.png")

    assert (found, total) == ([], 0)


async def test_percent_is_not_a_wildcard(db) -> None:
    """A URL-encoded character in a filename must not match everything."""
    await _page_using(db, "/media/pagebuilder/unrelated.png", title="Unrelated")

    found, total = await media_usage.find(db, "/media/pagebuilder/%.png")

    assert (found, total) == ([], 0)


async def test_the_real_url_still_matches(db) -> None:
    """The escaping must not break the ordinary case."""
    url = "/media/pagebuilder/hero_1.png"
    await _page_using(db, url, title="Genuine user")

    found, total = await media_usage.find(db, url)

    assert total == 1
    assert found[0].title == "Genuine user"
