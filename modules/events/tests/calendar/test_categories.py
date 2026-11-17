"""The category service."""

from __future__ import annotations

import pytest
from sm_events.calendar import categories
from sm_events.core.clock import utcnow
from sm_events.core.errors import Invalid, SlugTaken, UnknownLocale
from sm_events.models import Calendar, Category, Event
from sm_events.web.schemas.categories import CategoryCreate, CategoryPatch
from sqlalchemy import text

LOCALES = ("en", "de")


async def test_create_derives_slug_from_default_locale_name(db):
    cat = await categories.create_category(
        db, CategoryCreate(names={"de": "Konzert", "en": "Concert"}), locales=LOCALES
    )
    assert cat.slug == "concert"
    assert cat.names == {"de": "Konzert", "en": "Concert"}
    twin = await categories.create_category(
        db, CategoryCreate(names={"en": "Concert"}), locales=LOCALES
    )
    assert twin.slug == "concert-2"


async def test_unknown_locale_is_refused(db):
    with pytest.raises(UnknownLocale):
        await categories.create_category(
            db, CategoryCreate(names={"en": "A", "fr": "B"}), locales=LOCALES
        )


async def test_default_locale_name_required(db):
    with pytest.raises(Invalid):
        await categories.create_category(db, CategoryCreate(names={"de": "Nur"}), locales=LOCALES)


async def test_explicit_taken_slug_is_conflict(db):
    await categories.create_category(
        db, CategoryCreate(slug="music", names={"en": "Music"}), locales=LOCALES
    )
    with pytest.raises(SlugTaken):
        await categories.create_category(
            db, CategoryCreate(slug="music", names={"en": "Other"}), locales=LOCALES
        )


async def test_update_and_list_ordered_by_slug(db):
    b = await categories.create_category(db, CategoryCreate(names={"en": "B"}), locales=LOCALES)
    await categories.create_category(db, CategoryCreate(names={"en": "A"}), locales=LOCALES)
    await categories.update_category(
        db, b, CategoryPatch(names={"en": "Bee", "de": "Biene"}, color="#112233"), locales=LOCALES
    )
    listed = await categories.list_categories(db)
    assert [c.slug for c in listed] == ["a", "b"]
    assert (b.names["de"], b.color) == ("Biene", "#112233")
    with pytest.raises(UnknownLocale):
        await categories.update_category(db, b, CategoryPatch(names={"fr": "x"}), locales=LOCALES)
    with pytest.raises(Invalid):
        await categories.update_category(db, b, CategoryPatch(names={"de": "x"}), locales=LOCALES)


async def test_delete_nulls_events_category(db):
    cat = await categories.create_category(db, CategoryCreate(names={"en": "A"}), locales=LOCALES)
    cal = Calendar(slug="c", name="C", owner_id="o")
    db.add(cal)
    await db.flush()
    event = Event(
        uid="u",
        calendar_id=cal.id,
        category_id=cat.id,
        starts_at=utcnow(),
        ends_at=utcnow(),
        timezone="UTC",
    )
    db.add(event)
    await db.flush()
    await categories.delete_category(db, cat)
    await db.refresh(event)
    assert event.category_id is None
    assert (await db.execute(text("select count(*) from events_category"))).scalar_one() == 0


@pytest.mark.parametrize("count", [500, 501])
async def test_category_list_is_capped_at_500(db, count):
    db.add_all(Category(slug=f"c-{i:03d}", names={"en": "C"}) for i in range(count))
    await db.flush()
    rows = await categories.list_categories(db)
    assert [row.slug for row in rows] == [f"c-{i:03d}" for i in range(500)]
