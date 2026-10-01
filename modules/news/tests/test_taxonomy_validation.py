"""Taxonomy write validation: BUG-002/003/004/005/015 regressions."""

from __future__ import annotations

import pytest
from factories import make_article
from news.constants import ROUTE_PREFIX_API
from news.slugify import tag_slug

pytestmark = pytest.mark.asyncio

CATS = f"{ROUTE_PREFIX_API}/taxonomy/categories"
TAGS = f"{ROUTE_PREFIX_API}/taxonomy/tags"


async def _cat(client, name: str, **extra) -> dict:
    response = await client.post(CATS, json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def _tag(client, name: str):
    return await client.post(TAGS, json={"name": name})


class TestCategorySlugs:
    @pytest.mark.parametrize("slug", ["---", "!!!"])
    async def test_unusable_slug_is_422(self, editor_client, slug) -> None:
        cat = await _cat(editor_client, "Alpha")
        response = await editor_client.put(f"{CATS}/{cat['id']}", json={"slug": slug})
        assert response.status_code == 422

    async def test_slug_is_normalised(self, editor_client) -> None:
        cat = await _cat(editor_client, "Alpha")
        response = await editor_client.put(f"{CATS}/{cat['id']}", json={"slug": "Bad Slug"})
        assert response.status_code == 200
        assert response.json()["slug"] == "bad-slug"

    async def test_taken_slug_is_409(self, editor_client) -> None:
        await _cat(editor_client, "Alpha")
        other = await _cat(editor_client, "Beta")
        response = await editor_client.put(f"{CATS}/{other['id']}", json={"slug": "Alpha"})
        assert response.status_code == 409
        assert response.json()["detail"] == "That address is already used by another category."

    async def test_own_slug_is_not_a_clash(self, editor_client) -> None:
        cat = await _cat(editor_client, "Alpha")
        response = await editor_client.put(f"{CATS}/{cat['id']}", json={"slug": "alpha"})
        assert response.status_code == 200

    async def test_create_with_taken_slug_is_409(self, editor_client) -> None:
        await _cat(editor_client, "Alpha")
        response = await editor_client.post(CATS, json={"name": "Other", "slug": "alpha"})
        assert response.status_code == 409


class TestCategoryNames:
    async def test_blank_name_is_422(self, editor_client) -> None:
        response = await editor_client.post(CATS, json={"name": "   "})
        assert response.status_code == 422

    async def test_name_is_trimmed(self, editor_client) -> None:
        assert (await _cat(editor_client, "  FV Trim  "))["name"] == "FV Trim"

    async def test_create_is_case_insensitive(self, editor_client) -> None:
        await _cat(editor_client, "FV UI one")
        response = await editor_client.post(CATS, json={"name": " fv ui ONE "})
        assert response.status_code == 409

    async def test_rename_case_variant_of_itself_is_allowed(self, editor_client) -> None:
        cat = await _cat(editor_client, "alpha")
        response = await editor_client.put(f"{CATS}/{cat['id']}", json={"name": "Alpha"})
        assert response.status_code == 200


class TestTags:
    async def test_rename_to_existing_name_is_409(self, editor_client) -> None:
        await _tag(editor_client, "Urban")
        other = (await _tag(editor_client, "Rural")).json()
        response = await editor_client.put(f"{TAGS}/{other['id']}", json={"name": "Urban"})
        assert response.status_code == 409

    async def test_rename_to_blank_is_422(self, editor_client) -> None:
        tag = (await _tag(editor_client, "Rural")).json()
        response = await editor_client.put(f"{TAGS}/{tag['id']}", json={"name": "   "})
        assert response.status_code == 422

    async def test_rename_to_own_case_variant_is_allowed(self, editor_client) -> None:
        tag = (await _tag(editor_client, "rural")).json()
        response = await editor_client.put(f"{TAGS}/{tag['id']}", json={"name": "Rural"})
        assert response.status_code == 200

    async def test_unicode_tags_are_distinct_real_tags(self, editor_client) -> None:
        await _tag(editor_client, "item")
        zh = (await _tag(editor_client, "中文")).json()
        ar = (await _tag(editor_client, "العربية")).json()
        assert zh["name"] == "中文"
        assert ar["name"] == "العربية"
        assert len({zh["id"], ar["id"]}) == 2
        assert zh["slug"] == "中文"

    @pytest.mark.parametrize("name", ["???", "😀", "   "])
    async def test_no_letters_is_422(self, editor_client, name) -> None:
        await _tag(editor_client, "item")
        response = await _tag(editor_client, name)
        assert response.status_code == 422

    async def test_article_tags_keep_unicode_and_reject_symbols(self, editor_client) -> None:
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(db, slug="a", title="A")
            article_id = article.id
        url = f"{ROUTE_PREFIX_API}/articles/{article_id}/tags"
        ok = await editor_client.put(url, json={"tags": ["中文", "plain"]})
        assert ok.status_code == 200
        assert "中文" in ok.json()
        bad = await editor_client.put(url, json={"tags": ["???"]})
        assert bad.status_code == 422
        assert bad.json()["detail"] == "A tag needs at least one letter or number."


async def test_tag_slug_rules() -> None:
    assert tag_slug("Field  Notes!") == "field-notes"
    assert tag_slug("中文") == "中文"
    assert tag_slug("???") == ""
    assert tag_slug("snake_case") == "snake-case"
