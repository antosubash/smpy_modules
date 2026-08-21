"""``/p/{slug}`` answers as two representations and must validate them apart.

The route returns an HTML document or an Inertia JSON payload for the same URL,
chosen on the request's ``X-Inertia`` header. It used to derive one ETag from
the page row alone and stamp it on whichever one it produced, alongside
``Cache-Control: public``. A client holding the payload could then revalidate a
*document* request against that shared validator, get a 304, and go on
rendering the JSON as the page.

Not hypothetical: on a live site, following a link to a page and then opening
the same URL directly rendered ``{"component":"PageBuilder/PublicPage",...}``
in the browser, straight out of the HTTP cache.

RFC 9110 §8.8.1 requires distinct representations to carry distinct validators,
which is precisely the property that was missing.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
_SLUG = "cached"


async def _publish(client: AsyncClient) -> None:
    created = await client.post(
        "/api/pagebuilder/pages",
        json={"title": "Cached", "slug": _SLUG, "draft_data": {"content": ["body"]}},
    )
    assert created.status_code == 201, created.text
    published = await client.post(f"/api/pagebuilder/pages/{created.json()['id']}/publish")
    assert published.status_code == 200


def _vary(response) -> set[str]:
    return {part.strip().lower() for part in response.headers.get("vary", "").split(",")}


class TestValidatorsAreDistinct:
    async def test_the_two_representations_do_not_share_an_etag(
        self, authed_client: AsyncClient
    ) -> None:
        await _publish(authed_client)

        document = await authed_client.get(f"/p/{_SLUG}")
        payload = await authed_client.get(f"/p/{_SLUG}", headers=_INERTIA)

        assert document.headers["ETag"] != payload.headers["ETag"]

    async def test_a_payload_etag_does_not_revalidate_a_page_request(
        self, authed_client: AsyncClient
    ) -> None:
        """The bug, stated directly: JSON in hand, asking for the page."""
        await _publish(authed_client)
        payload = await authed_client.get(f"/p/{_SLUG}", headers=_INERTIA)

        document = await authed_client.get(
            f"/p/{_SLUG}", headers={"If-None-Match": payload.headers["ETag"]}
        )

        assert document.status_code == 200
        assert document.headers["content-type"].startswith("text/html")

    async def test_a_document_etag_does_not_revalidate_a_payload_request(
        self, authed_client: AsyncClient
    ) -> None:
        await _publish(authed_client)
        document = await authed_client.get(f"/p/{_SLUG}")

        payload = await authed_client.get(
            f"/p/{_SLUG}",
            headers={**_INERTIA, "If-None-Match": document.headers["ETag"]},
        )

        assert payload.status_code == 200


class TestConditionalRequestsStillWork:
    async def test_a_document_revalidates_against_its_own_etag(
        self, authed_client: AsyncClient
    ) -> None:
        """Splitting the validators must not cost the document its 304."""
        await _publish(authed_client)
        first = await authed_client.get(f"/p/{_SLUG}")

        second = await authed_client.get(
            f"/p/{_SLUG}", headers={"If-None-Match": first.headers["ETag"]}
        )

        assert second.status_code == 304

    async def test_a_payload_revalidates_against_its_own_etag(
        self, authed_client: AsyncClient
    ) -> None:
        await _publish(authed_client)
        first = await authed_client.get(f"/p/{_SLUG}", headers=_INERTIA)

        second = await authed_client.get(
            f"/p/{_SLUG}", headers={**_INERTIA, "If-None-Match": first.headers["ETag"]}
        )

        assert second.status_code == 304


class TestCachesAreToldWhatSelects:
    @pytest.mark.parametrize("headers", [{}, _INERTIA], ids=["document", "payload"])
    async def test_both_representations_vary_on_x_inertia(
        self, authed_client: AsyncClient, headers: dict
    ) -> None:
        await _publish(authed_client)

        response = await authed_client.get(f"/p/{_SLUG}", headers=headers)

        assert "x-inertia" in _vary(response)

    async def test_the_payload_keeps_the_vary_it_already_had(
        self, authed_client: AsyncClient
    ) -> None:
        """Appended, not assigned — `Accept` is what caches key on today."""
        await _publish(authed_client)

        response = await authed_client.get(f"/p/{_SLUG}", headers=_INERTIA)

        assert "accept" in _vary(response)


class TestOnlyTheDocumentIsShareable:
    async def test_the_payload_is_never_stored(self, authed_client: AsyncClient) -> None:
        """It carries the viewer's auth block, permissions and menus."""
        await _publish(authed_client)

        response = await authed_client.get(f"/p/{_SLUG}", headers=_INERTIA)

        assert response.headers["Cache-Control"] == "private, no-store"

    async def test_the_document_stays_publicly_cacheable(self, authed_client: AsyncClient) -> None:
        """Public page content caching was never the bug — keep it."""
        await _publish(authed_client)

        response = await authed_client.get(f"/p/{_SLUG}")

        assert "public" in response.headers["Cache-Control"]
