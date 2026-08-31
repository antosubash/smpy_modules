"""Starting a page's counterpart in another language.

Split from ``test_multilingual`` for the repo's 300-line cap. That file covers
the two things the *schema* change made true — per-language slugs and the
locale-prefixed address — and this one covers the operation built on top of
them.

The operation is deliberately small, because a translation is an ordinary page:
publishing it, scheduling it, rejecting it and restoring one of its revisions
all worked the day the column landed. What is left is joining the group,
seeding the draft, and the handful of fields that must or must not come across.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"


async def _page(client: AsyncClient, *, slug: str, locale: str | None = None, **extra) -> dict:
    body = {"title": extra.pop("title", slug), "slug": slug, "draft_data": {"content": []}}
    if locale is not None:
        body["locale"] = locale
    body.update(extra)
    response = await client.post(API, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _publish(client: AsyncClient, page_id: int) -> None:
    response = await client.post(f"{API}/{page_id}/publish")
    assert response.status_code == 200, response.text


class TestCreatingATranslation:
    async def test_it_joins_the_group_and_starts_as_a_draft(
        self, bilingual_client: AsyncClient
    ) -> None:
        """A translation going live the moment it is created would publish
        untranslated copy at a URL that did not exist a second earlier."""
        source = await _page(bilingual_client, slug="about", locale="en", title="About us")
        await _publish(bilingual_client, source["id"])

        response = await bilingual_client.post(
            f"{API}/{source['id']}/translations", json={"locale": "de"}
        )

        assert response.status_code == 201, response.text
        created = response.json()
        assert created["locale"] == "de"
        assert created["status"] == "draft"
        assert created["translation_group"] == source["translation_group"]

    async def test_it_copies_the_layout_and_the_untranslated_title(
        self, bilingual_client: AsyncClient
    ) -> None:
        """A translator replaces copy; they should not have to rebuild a page.
        The title comes across untranslated on purpose — an empty heading is
        not a better starting point than the original text."""
        source = await _page(
            bilingual_client,
            slug="about",
            locale="en",
            title="About us",
            draft_data={"content": [{"type": "Text"}]},
        )

        created = (
            await bilingual_client.post(
                f"{API}/{source['id']}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["title"] == "About us"
        assert created["draft_data"] == {"content": [{"type": "Text"}]}

    async def test_the_slug_is_reused_because_it_is_free(
        self, bilingual_client: AsyncClient
    ) -> None:
        source = await _page(bilingual_client, slug="about", locale="en")

        created = (
            await bilingual_client.post(
                f"{API}/{source['id']}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["slug"] == "about"

    async def test_a_taken_slug_gets_a_free_variant(
        self, bilingual_client: AsyncClient
    ) -> None:
        """Only when an *unrelated* German page already holds the word."""
        await _page(bilingual_client, slug="about", locale="de", title="Unrelated")
        source = await _page(bilingual_client, slug="about", locale="en")

        created = (
            await bilingual_client.post(
                f"{API}/{source['id']}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["slug"] == "about-2"

    async def test_a_second_one_in_the_same_language_is_refused(
        self, bilingual_client: AsyncClient
    ) -> None:
        """A double submit or a stale tab would otherwise produce two German
        siblings, and every alternates list would start contradicting itself."""
        source = await _page(bilingual_client, slug="about", locale="en")
        await bilingual_client.post(f"{API}/{source['id']}/translations", json={"locale": "de"})

        again = await bilingual_client.post(
            f"{API}/{source['id']}/translations", json={"locale": "de"}
        )

        assert again.status_code == 409

    async def test_translating_into_its_own_language_is_refused(
        self, bilingual_client: AsyncClient
    ) -> None:
        source = await _page(bilingual_client, slug="about", locale="en")

        response = await bilingual_client.post(
            f"{API}/{source['id']}/translations", json={"locale": "en"}
        )

        assert response.status_code == 409

    async def test_the_source_lists_the_translation_afterwards(
        self, bilingual_client: AsyncClient
    ) -> None:
        source = await _page(bilingual_client, slug="about", locale="en")
        await bilingual_client.post(f"{API}/{source['id']}/translations", json={"locale": "de"})

        detail = (await bilingual_client.get(f"{API}/{source['id']}")).json()

        assert sorted(t["locale"] for t in detail["translations"]) == ["de", "en"]

    async def test_the_parent_becomes_the_parents_own_counterpart(
        self, bilingual_client: AsyncClient
    ) -> None:
        """Breadcrumbs must not cross languages: a German page whose parent is
        the English one sends a reader out of their language mid-trail."""
        parent = await _page(bilingual_client, slug="handbook", locale="en")
        child = await _page(bilingual_client, slug="chapter", locale="en", parent_id=parent["id"])
        german_parent = (
            await bilingual_client.post(
                f"{API}/{parent['id']}/translations", json={"locale": "de"}
            )
        ).json()

        german_child = (
            await bilingual_client.post(
                f"{API}/{child['id']}/translations", json={"locale": "de"}
            )
        ).json()

        assert german_child["parent_id"] == german_parent["id"]

    async def test_a_canonical_url_is_never_inherited(
        self, bilingual_client: AsyncClient
    ) -> None:
        """Copying it would make every translation declare the source as its
        canonical — telling search engines the translations are duplicates."""
        source = await _page(
            bilingual_client, slug="about", locale="en", canonical_url="https://x.test/about"
        )

        created = (
            await bilingual_client.post(
                f"{API}/{source['id']}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["canonical_url"] is None


class TestATrashedCounterpart:
    """``(translation_group, locale)`` is unique regardless of ``deleted_at``.

    So a trashed translation still occupies its language. The editor's panel is
    built from ``detail().translations``; if that list dropped trashed rows the
    panel would show the language as free and offer a button whose only
    possible outcome is the 409 below.
    """

    async def test_it_still_occupies_the_language(
        self, bilingual_client: AsyncClient
    ) -> None:
        source = await _page(bilingual_client, slug="about", locale="en")
        german = (
            await bilingual_client.post(
                f"{API}/{source['id']}/translations", json={"locale": "de"}
            )
        ).json()

        assert (await bilingual_client.delete(f"{API}/{german['id']}")).status_code == 204

        refused = await bilingual_client.post(
            f"{API}/{source['id']}/translations", json={"locale": "de"}
        )
        assert refused.status_code == 409

        detail = (await bilingual_client.get(f"{API}/{source['id']}")).json()
        german_row = next(t for t in detail["translations"] if t["locale"] == "de")
        assert german_row["trashed"] is True

    async def test_a_live_counterpart_is_not_flagged(
        self, bilingual_client: AsyncClient
    ) -> None:
        """The flag has to distinguish, or the panel labels every sibling
        "In trash" and no language is ever openable."""
        source = await _page(bilingual_client, slug="about", locale="en")
        await bilingual_client.post(f"{API}/{source['id']}/translations", json={"locale": "de"})

        detail = (await bilingual_client.get(f"{API}/{source['id']}")).json()
        assert all(t["trashed"] is False for t in detail["translations"])
