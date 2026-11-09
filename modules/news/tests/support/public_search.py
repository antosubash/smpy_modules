"""Searching the public archive.

``/api/news/articles?q=`` was anonymous and the admin had a whole search screen,
but a reader browsing ``/news/`` could only page or narrow by category or tag:
the capability was built and simply not offered to the people most likely to
want it.

What these tests pin is the *shape* of the answer rather than the fact of it.
A search is an address (``/news/?q=…``), so it can be linked and paged. It
composes with everything else that narrows the archive rather than replacing
it. It obeys the archive's visibility rule, so no search reaches a draft. And
it is not indexable, because the input space is unbounded.
"""

from __future__ import annotations

from tests.support.factories import make_article

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def _seed(client, slug: str, **kwargs):
    kwargs.setdefault("title", slug)
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, **kwargs)


async def _props(client, path: str) -> dict:
    response = await client.get(path, headers=INERTIA)
    assert response.status_code == 200, response.text
    return response.json()["props"]
