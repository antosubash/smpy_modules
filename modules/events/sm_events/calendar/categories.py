"""Category reads and writes. No FastAPI, no commit (the request finishes the
transaction); a write that can lose a race on the slug flushes in a savepoint."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update
from sqlmodel import select

from sm_events.calendar.slugs import free_slug, slug_taken, slug_write, slugify
from sm_events.core import constants
from sm_events.core.errors import Invalid, NotFound, SlugTaken, UnknownLocale
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Category, Event
from sm_events.models.category import CATEGORY_SLUG_CONSTRAINT
from sm_events.web.schemas.categories import CategoryCreate, CategoryPatch


def _check_names(names: dict[str, str], locales: tuple[str, ...]) -> None:
    """Every key a content locale, and one for the default language."""
    if any(key not in locales for key in names):
        raise UnknownLocale
    if locales[0] not in names:
        raise Invalid(constants.DEFAULT_LOCALE_REQUIRED_DETAIL, code="default_locale_required")


async def list_categories(db: Any) -> list[Category]:
    stmt = select(Category).order_by(Category.slug).limit(constants.CATEGORIES_MAX)
    return list((await db.execute(stmt)).scalars().all())


async def get_category(db: Any, category_id: uuid.UUID) -> Category:
    row = (await db.execute(select(Category).where(Category.id == category_id))).scalars().first()
    if row is None:
        raise NotFound(constants.NOT_FOUND_DETAIL)
    return row


async def create_category(db: Any, data: CategoryCreate, *, locales: tuple[str, ...]) -> Category:
    """Insert a category. An explicit slug that is taken is a 409; one derived
    from the default language's name gets a ``-2``, ``-3``... suffix."""
    _check_names(data.names, locales)
    if data.slug is not None and await slug_taken(db, Category, data.slug):
        raise SlugTaken
    row = Category(
        slug=data.slug
        or await free_slug(
            db, Category, slugify(data.names[locales[0]], constants.CATEGORY_SLUG_FALLBACK)
        ),
        names=dict(data.names),
        color=data.color,
    )
    async with slug_write(db, CATEGORY_SLUG_CONSTRAINT):
        db.add(row)
    return row


async def update_category(
    db: Any, cat: Category, data: CategoryPatch, *, locales: tuple[str, ...]
) -> Category:
    fields = data.model_dump(exclude_unset=True)
    if "names" in fields:
        _check_names(fields["names"], locales)
        cat.names = dict(fields["names"])
    if "color" in fields:
        cat.color = fields["color"]
    await db.flush()
    return cat


async def delete_category(db: Any, cat: Category) -> None:
    """Null the category on its events, then delete it. Explicit: SQLite runs
    without foreign-key enforcement, so ``ON DELETE SET NULL`` cannot be relied
    on. A Core statement, so it pins the tenant itself."""
    await db.execute(
        update(Event)
        .where(Event.tenant_id == bound_tenant(), Event.category_id == cat.id)
        .values(category_id=None)
        # Restoring a trashed event must not revive a deleted category reference.
        .execution_options(include_deleted=True)
    )
    await db.delete(cat)
    await db.flush()
