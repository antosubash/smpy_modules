"""A slug a public route segment owns is refused, and never derived."""

from __future__ import annotations

import pytest
from sm_events.calendar import calendars, slugs
from sm_events.content.texts import apply_texts
from sm_events.core import constants
from sm_events.core.errors import SlugReserved
from sm_events.models import Category
from sm_events.web.schemas.calendars import CalendarCreate, CalendarPatch
from sm_events.web.schemas.texts import TextIn

from tests.support.access import principal, seed_calendars
from tests.support.calendars import bare_event
from tests.support.events_http import EV, OWNER, cast, create_json

RESERVED = constants.RESERVED_SLUGS
LOCALES = ("en", "de")
WHO = principal("o", "events.view", "events.edit")


def test_the_reserved_set():
    assert set(RESERVED) == {"api", "c", "calendar", "feed", "sitemap"}


@pytest.mark.parametrize("slug", RESERVED)
def test_check_not_reserved(slug):
    with pytest.raises(SlugReserved) as exc:
        slugs.check_not_reserved(slug)
    assert exc.value.code == "slug_reserved" and exc.value.status_code == 422
    slugs.check_not_reserved(f"{slug}-2")
    slugs.check_not_reserved(f"my-{slug}")


async def _event(db):
    cal = (await seed_calendars(db))["I"]
    return await bare_event(db, cal)


@pytest.mark.parametrize("slug", RESERVED)
async def test_event_text_reserved(db, slug):
    event = await _event(db)
    with pytest.raises(SlugReserved) as exc:
        await apply_texts(
            db, event, {"en": TextIn(title="Concert", slug=slug)}, locales=LOCALES, creating=True
        )
    assert exc.value.field == "texts.en.slug"
    # Nothing was written.
    assert (await slugs.text_slug_taken(db, "en", slug)) is False


@pytest.mark.parametrize("slug", RESERVED)
async def test_event_text_title_derivation_skips_reserved(db, slug):
    event = await _event(db)
    await apply_texts(db, event, {"en": TextIn(title=slug.title())}, locales=LOCALES, creating=True)
    await db.flush()
    from sm_events.content.texts import texts_of

    assert (await texts_of(db, [event.id]))[event.id]["en"].slug == f"{slug}-2"


async def test_event_text_reserved_on_update_too(db):
    event = await _event(db)
    await apply_texts(db, event, {"en": TextIn(title="Concert")}, locales=LOCALES, creating=True)
    with pytest.raises(SlugReserved):
        await apply_texts(
            db, event, {"en": TextIn(title="Concert", slug="feed")}, locales=LOCALES, creating=False
        )


@pytest.mark.parametrize("slug", RESERVED)
async def test_calendar_reserved(db, slug):
    with pytest.raises(SlugReserved):
        await calendars.create_calendar(
            db, WHO, CalendarCreate(name="Team", slug=slug), default_tz="UTC"
        )
    cal = await calendars.create_calendar(db, WHO, CalendarCreate(name="Team"), default_tz="UTC")
    with pytest.raises(SlugReserved):
        await calendars.update_calendar(db, cal, CalendarPatch(slug=slug))
    assert cal.slug == "team"


@pytest.mark.parametrize("slug", RESERVED)
async def test_calendar_derivation_skips_reserved(db, slug):
    cal = await calendars.create_calendar(
        db, WHO, CalendarCreate(name=slug.title()), default_tz="UTC"
    )
    assert cal.slug == f"{slug}-2"


async def test_categories_are_not_public_segments(db):
    """A category slug is a query value, not a path segment: ``calendar`` stays free."""
    assert await slugs.free_slug(db, Category, "calendar") == "calendar"


async def test_api_422(client):
    got = await client.post(
        "/api/events/calendars", json={"name": "Team", "slug": "c"}, headers=OWNER
    )
    assert got.status_code == 422
    assert got.json() == {"detail": constants.SLUG_RESERVED_DETAIL, "code": "slug_reserved"}


async def test_api_422_for_an_event_text(client):
    cal = (await cast(client))["I"]
    body = create_json(cal, texts={"en": {"title": "Concert", "slug": "sitemap"}})
    got = await client.post(EV, json=body, headers=OWNER)
    assert got.status_code == 422
    assert got.json()["code"] == "slug_reserved" and got.json()["field"] == "texts.en.slug"
