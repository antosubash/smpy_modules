"""The public viewer's cache headers follow the viewer, not just the page (#94).

Signed in, the page carries the visitor's ``auth.user`` and a greeting in the
header; in another UI language, every string in the chrome differs. Either way
a shared cache must not hand the response to someone else, and a revalidation
must not 304 against a response built for a different viewer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from pagebuilder.public_cache import cache_control, etag_for, viewer_key
from pagebuilder.settings import PagebuilderSettings

_WHEN = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _request(*, user: object | None = None, locale: str | None = "en") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=user, locale=locale))


def _etag(request: SimpleNamespace) -> str:
    return etag_for(1, _WHEN, viewer=viewer_key(request))  # type: ignore[arg-type]


def test_a_ui_locale_change_changes_the_etag() -> None:
    assert _etag(_request(locale="en")) != _etag(_request(locale="de"))


def test_signing_in_changes_the_etag() -> None:
    signed_in = _request(user=SimpleNamespace(id=7))
    assert _etag(_request()) != _etag(signed_in)


def test_two_signed_in_users_never_share_an_etag() -> None:
    alice = _request(user=SimpleNamespace(id=7))
    bob = _request(user=SimpleNamespace(id=8))
    assert _etag(alice) != _etag(bob)
    assert _etag(alice) == _etag(_request(user=SimpleNamespace(id=7)))


def test_the_viewer_key_does_not_leak_the_user_id() -> None:
    key = viewer_key(_request(user=SimpleNamespace(id="alice@example.com")))  # type: ignore[arg-type]
    assert "alice" not in key


def test_a_signed_in_response_is_private() -> None:
    policy = cache_control(_request(user=SimpleNamespace(id=7)), PagebuilderSettings())  # type: ignore[arg-type]
    assert policy == "private, no-store"


def test_an_anonymous_response_stays_public() -> None:
    settings = PagebuilderSettings(public_cache_max_age=60, public_cache_swr=600)
    policy = cache_control(_request(), settings)  # type: ignore[arg-type]
    assert policy == "public, max-age=60, stale-while-revalidate=600"


async def _publish(client: AsyncClient, slug: str = "hello") -> None:
    created = await client.post(
        "/api/pagebuilder/pages",
        json={"title": "Hello", "slug": slug, "draft_data": {"content": ["body"]}},
    )
    assert created.status_code == 201, created.text
    published = await client.post(f"/api/pagebuilder/pages/{created.json()['id']}/publish")
    assert published.status_code == 200, published.text


# conftest's stub auth leaves a request with this header signed out, so one app
# can publish as an admin and then be read by an anonymous visitor.
_ANON = {"X-Test-Anonymous": "1"}


@pytest.mark.asyncio
async def test_a_signed_in_visitor_gets_an_unstorable_response(
    authed_client: AsyncClient,
) -> None:
    """It embeds the user's name, roles and menus: kept nowhere, validated by nothing."""
    await _publish(authed_client)
    response = await authed_client.get("/p/hello")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "etag" not in response.headers


@pytest.mark.asyncio
async def test_an_anonymous_visitor_gets_a_public_response_that_varies(
    authed_client: AsyncClient,
) -> None:
    await _publish(authed_client)
    response = await authed_client.get("/p/hello", headers=_ANON)
    assert response.status_code == 200
    assert response.headers["Cache-Control"].startswith("public, max-age=")
    vary = {v.strip().lower() for v in response.headers["Vary"].split(",")}
    assert {"x-inertia", "cookie", "accept-language"} <= vary


@pytest.mark.asyncio
async def test_a_signed_in_request_is_never_answered_304(authed_client: AsyncClient) -> None:
    """Not even with the tag an anonymous copy of the page carries: the signed-in
    render differs (and the user's roles may have changed since any earlier one)."""
    await _publish(authed_client)
    anonymous = await authed_client.get("/p/hello", headers=_ANON)
    signed_in = await authed_client.get(
        "/p/hello", headers={"If-None-Match": anonymous.headers["ETag"]}
    )
    assert signed_in.status_code == 200
    assert signed_in.headers["Cache-Control"] == "private, no-store"


@pytest.mark.asyncio
async def test_an_anonymous_304_keeps_the_public_policy(authed_client: AsyncClient) -> None:
    await _publish(authed_client)
    first = await authed_client.get("/p/hello", headers=_ANON)
    again = await authed_client.get(
        "/p/hello", headers={**_ANON, "If-None-Match": first.headers["ETag"]}
    )
    assert again.status_code == 304
    assert again.headers["Cache-Control"].startswith("public, max-age=")
    assert again.headers["ETag"] == first.headers["ETag"]
