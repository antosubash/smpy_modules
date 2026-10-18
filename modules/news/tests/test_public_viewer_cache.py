"""A rendered public page's cache headers follow the viewer, not just the URL (#94).

The article and the archive carry Inertia's shared ``auth.user`` and chrome in
the visitor's UI language, so a signed-in reader's copy must never be stored
where another reader could be served it, and a revalidation must never 304
against a copy built for someone else.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from factories import make_article
from news.endpoints.public._urls import etag_for, viewer_key

pytestmark = pytest.mark.asyncio

NEWS = "/news"


def _request(*, user: object | None = None, locale: str = "en") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=user, locale=locale))


def _etag(request: SimpleNamespace) -> str:
    return etag_for(1, None, "html", viewer_key(request))  # type: ignore[arg-type]


async def _seed(client, slug: str = "hello"):
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, title=slug, category="Sport")


async def test_the_etag_changes_with_the_ui_locale_and_the_reader() -> None:
    anon_en, anon_de = _etag(_request()), _etag(_request(locale="de"))
    alice = _etag(_request(user=SimpleNamespace(id=7)))
    bob = _etag(_request(user=SimpleNamespace(id=8)))
    assert len({anon_en, anon_de, alice, bob}) == 4


async def test_the_viewer_key_does_not_carry_the_user_id() -> None:
    assert "alice" not in viewer_key(_request(user=SimpleNamespace(id="alice@x.org")))  # type: ignore[arg-type]


async def test_a_signed_in_reader_gets_a_private_article(editor_public_client) -> None:
    await _seed(editor_public_client)
    response = await editor_public_client.get(f"{NEWS}/hello")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-cache"
    again = await editor_public_client.get(
        f"{NEWS}/hello", headers={"If-None-Match": response.headers["etag"]}
    )
    assert (again.status_code, again.headers["cache-control"]) == (304, "private, no-cache")


async def test_a_signed_in_reader_gets_a_private_archive(editor_public_client) -> None:
    await _seed(editor_public_client)
    response = await editor_public_client.get(f"{NEWS}/category/Sport")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-cache"


async def test_an_anonymous_reader_still_gets_public_pages(anon_client) -> None:
    await _seed(anon_client)
    for path in (f"{NEWS}/hello", f"{NEWS}/category/Sport"):
        response = await anon_client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert response.headers["cache-control"].startswith("public, max-age="), path
