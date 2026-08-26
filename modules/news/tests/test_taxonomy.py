"""Categories and tags — the behaviour the management screen depends on.

The cases here are the ones where a naive implementation is wrong rather than
merely untested: renaming has to carry the articles, deleting must not take
articles with it, and merging has to survive an article that already carries
both tags.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import category_service, service, tag_service
from news.constants import UNCATEGORISED_LABEL
from news.models import ArticleStatus, NewsArticle
from sqlmodel import select

pytestmark = pytest.mark.asyncio


async def _article(db, slug: str, category: str, *, status=ArticleStatus.PUBLISHED):
    return await make_article(db, slug=slug, title=slug, status=status, category=category)


class TestCategoryListing:
    async def test_uncategorised_is_always_present_and_last(self, db) -> None:
        await _article(db, "a", "Research")

        items = await category_service.list_categories(db)

        assert items[-1].name == UNCATEGORISED_LABEL
        assert items[-1].is_system is True

    async def test_free_text_categories_still_list(self, db) -> None:
        """A category typed on an article but never formalised must not vanish."""
        await _article(db, "a", "Improvised")

        names = [c.name for c in await category_service.list_categories(db)]

        assert "Improvised" in names

    async def test_counts_include_drafts(self, db) -> None:
        """The editor's screen: a category of drafts still has real weight."""
        await _article(db, "d", "Research", status=ArticleStatus.DRAFT)

        found = next(
            c for c in await category_service.list_categories(db) if c.name == "Research"
        )

        assert found.article_count == 1

    async def test_managed_categories_sort_before_free_text_ones(self, db) -> None:
        await _article(db, "a", "Zebra")
        await category_service.create(db, name="Zebra")
        await _article(db, "b", "Apple")

        names = [c.name for c in await category_service.list_categories(db)]

        assert names.index("Zebra") < names.index("Apple")


class TestCategoryRename:
    async def test_carries_its_articles(self, db) -> None:
        """The rename is a bulk update; without it every article is orphaned."""
        await _article(db, "a", "Field notes")
        await _article(db, "b", "Field notes")
        category = await category_service.create(db, name="Field notes")

        await category_service.rename(db, category, name="Field reports")

        rows = (await db.execute(select(NewsArticle.category))).scalars().all()
        assert set(rows) == {"Field reports"}

    async def test_leaves_other_categories_alone(self, db) -> None:
        await _article(db, "a", "Research")
        await _article(db, "b", "Interviews")
        category = await category_service.create(db, name="Research")

        await category_service.rename(db, category, name="Studies")

        rows = sorted((await db.execute(select(NewsArticle.category))).scalars().all())
        assert rows == ["Interviews", "Studies"]

    async def test_slug_can_change_without_touching_the_name(self, db) -> None:
        category = await category_service.create(db, name="Field notes")

        updated = await category_service.rename(db, category, slug="Notes From The Field")

        assert updated.name == "Field notes"
        assert updated.slug == "notes-from-the-field"


class TestCategoryDelete:
    async def test_moves_articles_to_uncategorised_by_default(self, db) -> None:
        await _article(db, "a", "Research")
        category = await category_service.create(db, name="Research")

        moved = await category_service.delete(db, category)

        assert moved == 1
        rows = (await db.execute(select(NewsArticle.category))).scalars().all()
        assert rows == [""]

    async def test_reassigns_to_a_named_category(self, db) -> None:
        await _article(db, "a", "Research")
        await category_service.create(db, name="Studies")
        category = await category_service.create(db, name="Research")

        await category_service.delete(db, category, reassign_to="Studies")

        rows = (await db.execute(select(NewsArticle.category))).scalars().all()
        assert rows == ["Studies"]

    async def test_never_deletes_an_article(self, db) -> None:
        await _article(db, "a", "Research")
        category = await category_service.create(db, name="Research")

        await category_service.delete(db, category)

        remaining = (await db.execute(select(NewsArticle))).scalars().all()
        assert len(remaining) == 1


class TestCategoryOrdering:
    async def test_reorder_writes_positions_in_the_order_given(self, db) -> None:
        first = await category_service.create(db, name="A")
        second = await category_service.create(db, name="B")
        third = await category_service.create(db, name="C")

        await category_service.reorder(db, [third.id, first.id, second.id])

        items = await category_service.list_categories(db)
        assert [c.name for c in items if not c.is_system] == ["C", "A", "B"]

    async def test_public_listing_follows_the_managed_order(self, db) -> None:
        """The screen's promise: this order is the public filter bar's order."""
        await _article(db, "a", "Zebra")
        await _article(db, "b", "Apple")
        zebra = await category_service.create(db, name="Zebra")
        apple = await category_service.create(db, name="Apple")
        await category_service.reorder(db, [zebra.id, apple.id])

        listed = await service.list_categories(db)

        assert [c.category for c in listed] == ["Zebra", "Apple"]


class TestCategorySlugFiltering:
    async def test_listing_accepts_a_slug_as_well_as_a_name(self, db) -> None:
        await _article(db, "a", "Field notes")
        await category_service.create(db, name="Field notes")

        items, total = await service.list_articles(db, category="field-notes")

        assert total == 1
        assert items[0].category == "Field notes"


class TestTags:
    async def test_get_or_create_matches_on_slug_not_spelling(self, db) -> None:
        first = await tag_service.get_or_create(db, "Urban")
        second = await tag_service.get_or_create(db, " urban ")

        assert first.id == second.id

    async def test_set_for_article_replaces_rather_than_merges(self, db) -> None:
        article = await _article(db, "a", "Research")
        await tag_service.set_for_article(db, article.id, ["canopy", "urban"])

        await tag_service.set_for_article(db, article.id, ["canopy"])

        assert await tag_service.list_for_article(db, article.id) == ["canopy"]

    async def test_counts_reflect_usage(self, db) -> None:
        one = await _article(db, "a", "Research")
        two = await _article(db, "b", "Research")
        await tag_service.set_for_article(db, one.id, ["canopy"])
        await tag_service.set_for_article(db, two.id, ["canopy"])

        counts = {t.name: t.article_count for t in await tag_service.list_tags(db)}

        assert counts["canopy"] == 2

    async def test_unused_tags_still_list(self, db) -> None:
        """These are exactly the rows the screen fades and offers to merge."""
        await tag_service.get_or_create(db, "orphan")

        assert [t.name for t in await tag_service.list_tags(db)] == ["orphan"]

    async def test_merge_survives_an_article_carrying_both_tags(self, db) -> None:
        """The case a bulk UPDATE cannot do: it collides on the primary key."""
        both = await _article(db, "a", "Research")
        source_only = await _article(db, "b", "Research")
        await tag_service.set_for_article(db, both.id, ["canopy", "trees"])
        await tag_service.set_for_article(db, source_only.id, ["trees"])
        tags = {t.name: t.id for t in await tag_service.list_tags(db)}
        source = await tag_service.get(db, tags["trees"])
        target = await tag_service.get(db, tags["canopy"])

        moved = await tag_service.merge(db, source=source, target=target)

        assert moved == 2
        assert await tag_service.list_for_article(db, both.id) == ["canopy"]
        assert await tag_service.list_for_article(db, source_only.id) == ["canopy"]
        assert [t.name for t in await tag_service.list_tags(db)] == ["canopy"]

    async def test_names_for_articles_is_one_query_per_call(self, db) -> None:
        one = await _article(db, "a", "Research")
        two = await _article(db, "b", "Research")
        await tag_service.set_for_article(db, one.id, ["canopy"])
        await tag_service.set_for_article(db, two.id, ["urban"])

        found = await tag_service.names_for_articles(db, [one.id, two.id])

        assert found == {one.id: ["canopy"], two.id: ["urban"]}

    async def test_names_for_articles_handles_an_empty_list(self, db) -> None:
        assert await tag_service.names_for_articles(db, []) == {}
