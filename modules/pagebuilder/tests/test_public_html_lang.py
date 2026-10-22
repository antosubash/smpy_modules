"""``<html lang>`` on a public page is the page's language (#187).

The host shell hard-codes ``lang="en"``, so without the rewrite a German page
reached screen readers, browser translation offers and search engines as
English, whatever its ``hreflang`` alternates said.
"""

from __future__ import annotations

import pytest
from fastapi.responses import HTMLResponse
from httpx import AsyncClient
from pagebuilder.html_lang import set_html_lang

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"


async def _published_pair(client: AsyncClient) -> None:
    source = (
        await client.post(
            API, json={"title": "About us", "slug": "about", "draft_data": {"content": []}}
        )
    ).json()
    translation = (
        await client.post(f"{API}/{source['id']}/translations", json={"locale": "de"})
    ).json()
    for page in (source, translation):
        assert (await client.post(f"{API}/{page['id']}/publish")).status_code == 200


class TestHtmlLang:
    async def test_a_german_page_is_served_as_german(self, bilingual_client: AsyncClient) -> None:
        await _published_pair(bilingual_client)

        response = await bilingual_client.get("/de/p/about")

        assert response.status_code == 200
        assert '<html lang="de" data-shell-lang="en">' in response.text
        # The body changed length; a stale header would truncate the document.
        assert int(response.headers["content-length"]) == len(response.content)

    async def test_the_default_language_is_served_as_english(
        self, bilingual_client: AsyncClient
    ) -> None:
        await _published_pair(bilingual_client)

        response = await bilingual_client.get("/p/about")

        assert '<html lang="en" data-shell-lang="en">' in response.text

    async def test_an_inertia_visit_is_left_alone(self, bilingual_client: AsyncClient) -> None:
        """A JSON page object has no shell to rewrite; ``useDocumentLang`` sets
        the attribute for client-side visits instead."""
        await _published_pair(bilingual_client)

        response = await bilingual_client.get(
            "/de/p/about", headers={"X-Inertia": "true", "X-Inertia-Version": "1.0"}
        )

        assert response.json()["props"]["locale"] == "de"
        assert "data-shell-lang" not in response.text


class TestRewrite:
    """``set_html_lang`` on its own: what it writes and what it refuses to touch."""

    @staticmethod
    def _shell(body: bytes) -> HTMLResponse:
        return HTMLResponse(content=body)

    async def test_a_hostile_locale_cannot_leave_the_attribute(self) -> None:
        # Stored locales are pattern-checked; this is the second line behind it.
        response = set_html_lang(
            self._shell(b'<html lang="en"><body></body></html>'), 'de" onload="x'
        )

        assert response.body.startswith(
            b'<html lang="de&quot; onload=&quot;x" data-shell-lang="en">'
        )

    async def test_only_the_shell_tag_is_rewritten(self) -> None:
        body = b'<html lang="en"><body>&lt;html lang="fr"&gt;<html lang="fr"></body></html>'

        patched = set_html_lang(self._shell(body), "de").body

        assert patched.count(b"data-shell-lang") == 1
        assert patched.endswith(b'<html lang="fr"></body></html>')

    async def test_a_shell_without_lang_is_left_alone(self) -> None:
        body = b"<html><body></body></html>"

        assert set_html_lang(self._shell(body), "de").body == body
