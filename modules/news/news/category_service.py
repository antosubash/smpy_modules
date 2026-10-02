"""Category management behind ``/admin/news/categories``.

A category is a *name* carried on every article that belongs to it, plus an
optional row here giving that name a slug and an ordering — see
``models.NewsCategory`` for why it is not a foreign key. Two consequences shape
everything below:

* Renaming is a bulk update of the articles carrying the old name. It has to be
  atomic with the row update, or a failure between the two leaves articles
  pointing at a category name that no longer exists.
* A category can exist as free text on articles with no row here at all. Every
  listing unions the two sources, so a category an author typed while writing
  still shows up and can still be ordered later.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from news.constants import MAX_CATEGORY_LEN, UNCATEGORISED_LABEL
from news.contracts.schemas import CategoryRead
from news.models import NOT_TRASHED, NewsArticle, NewsCategory
from news.slugify import slugify, unique_slug

# Free-text categories sort after every ordered one. Large enough that no
# realistic hand-ordered list reaches it.
_UNORDERED_POSITION = 1_000_000


async def _taken_slugs(db: AsyncSession, *, excluding: int | None = None) -> set[str]:
    stmt = select(NewsCategory.slug)
    if excluding is not None:
        stmt = stmt.where(NewsCategory.id != excluding)
    return set((await db.execute(stmt)).scalars().all())


async def _counts(db: AsyncSession) -> dict[str, int]:
    """Article count per category name, drafts included but trash excluded.

    This is the editor's screen: a category holding nothing but drafts still
    has to show its true weight, or deleting it looks free when it is not.

    Trashed articles are the other half of that. Counting the raw rows would
    report articles no listing will show, and the editor deciding whether a
    category is safe to delete would read a number nothing on screen can
    account for.
    """
    rows = (
        await db.execute(
            select(NewsArticle.category, func.count())
            .select_from(NewsArticle)
            .where(NOT_TRASHED)
            .group_by(NewsArticle.category)
        )
    ).all()
    return {name: int(count) for name, count in rows}


async def list_categories(db: AsyncSession) -> list[CategoryRead]:
    """Ordered categories, then any free-text ones, then Uncategorised.

    Uncategorised is always last and always present, even at zero: it is the
    reassignment target the delete dialog offers, so hiding it when empty would
    remove the one destination that always exists.
    """
    counts = await _counts(db)
    rows = (
        await db.execute(select(NewsCategory).order_by(NewsCategory.position, NewsCategory.name))
    ).scalars().all()

    items = [
        CategoryRead(
            id=row.id or 0,
            name=row.name,
            slug=row.slug,
            position=row.position,
            article_count=counts.get(row.name, 0),
            is_system=False,
        )
        for row in rows
    ]

    known = {row.name for row in rows}
    for name in sorted(n for n in counts if n and n not in known):
        items.append(
            CategoryRead(
                id=0,
                name=name,
                slug=slugify(name, max_length=MAX_CATEGORY_LEN),
                position=_UNORDERED_POSITION,
                article_count=counts[name],
                # id 0 marks it as having no row yet; the screen offers to
                # formalise it rather than pretending it is editable.
                is_system=False,
            )
        )

    items.append(
        CategoryRead(
            id=0,
            name=UNCATEGORISED_LABEL,
            slug="",
            position=_UNORDERED_POSITION + 1,
            article_count=counts.get("", 0),
            is_system=True,
        )
    )
    return items


async def get(db: AsyncSession, category_id: int) -> NewsCategory | None:
    return await db.scalar(select(NewsCategory).where(NewsCategory.id == category_id))


async def get_by_name(db: AsyncSession, name: str) -> NewsCategory | None:
    return await db.scalar(select(NewsCategory).where(NewsCategory.name == name))


async def resolve_slug(db: AsyncSession, slug: str) -> str | None:
    """Category *name* for a slug, so public URLs can filter by slug.

    Returns ``None`` when no row matches — the caller then treats the value as
    a literal category name, which is what a free-text category needs.
    """
    return await db.scalar(select(NewsCategory.name).where(NewsCategory.slug == slug))


async def create(db: AsyncSession, *, name: str, slug: str | None = None) -> NewsCategory:
    """Add a category. Position lands it at the end of the order."""
    last = await db.scalar(select(func.max(NewsCategory.position)))
    resolved = (
        slugify(slug or name, max_length=MAX_CATEGORY_LEN)
        if slug
        else unique_slug(name, await _taken_slugs(db), max_length=MAX_CATEGORY_LEN)
    )
    category = NewsCategory(
        name=name, slug=resolved, position=(last or 0) + 1
    )
    db.add(category)
    await db.flush()
    await db.refresh(category)
    return category


async def rename(
    db: AsyncSession,
    category: NewsCategory,
    *,
    name: str | None = None,
    slug: str | None = None,
) -> NewsCategory:
    """Rename the category and carry every article that used the old name.

    The bulk update runs in the caller's transaction, so the row change and the
    article changes commit together or not at all. Without that, a failure in
    between would orphan every article in the category — they would carry a
    name no row matches, and the category would appear twice on the screen:
    once as the renamed row, once as free text.
    """
    if name is not None and name != category.name:
        await db.execute(
            sa_update(NewsArticle)
            .where(NewsArticle.category == category.name)
            .values(category=name)
        )
        category.name = name
    if slug is not None:
        category.slug = slugify(slug, max_length=MAX_CATEGORY_LEN)
    db.add(category)
    await db.flush()
    await db.refresh(category)
    return category


async def reorder(db: AsyncSession, ordered_ids: list[int]) -> None:
    """Write positions from the order the screen dragged them into.

    Ids not listed keep their position; the screen always sends the full list,
    but a stale client sending a subset must not silently reshuffle the rest.
    """
    for position, category_id in enumerate(ordered_ids):
        await db.execute(
            sa_update(NewsCategory)
            .where(NewsCategory.id == category_id)
            .values(position=position)
        )
    await db.flush()


async def delete(
    db: AsyncSession, category: NewsCategory, *, reassign_to: str = ""
) -> int:
    """Remove the category, moving its articles rather than deleting them.

    ``reassign_to`` is a category *name*; the empty string means Uncategorised,
    which is why it is the default — the one destination that always exists.
    Returns how many articles moved.

    Nothing here deletes an article. That is the promise the screen makes, and
    it is the reason this is a reassignment rather than a cascade.
    """
    result = await db.execute(
        sa_update(NewsArticle)
        .where(NewsArticle.category == category.name)
        .values(category=reassign_to)
    )
    await db.delete(category)
    await db.flush()
    return result.rowcount or 0
