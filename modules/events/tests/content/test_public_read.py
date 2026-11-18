"""Every public lookup goes through the gate."""

from __future__ import annotations

import pytest
from sm_events.content import public_read as read
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, EventText, Redirect
from sqlalchemy import func, select

from tests.support.calendars import PublicFixture, seed_public_fixture

ALL_EVENTS = [
    "one_off",
    "series",
    "draft",
    "in_review",
    "scheduled",
    "trashed",
    "conf",
    "talk",
    "secret_talk",
    "draft_parent",
    "orphan",
    "internal_event",
    "private_event",
    "gone_event",
]
PUBLIC = {"one_off", "series", "conf", "talk", "orphan"}


@pytest.mark.parametrize("name", ALL_EVENTS)
async def test_event_by_slug_only_public(db, name):
    fx = await seed_public_fixture(db)
    event = getattr(fx, name)
    found = await read.event_by_slug(db, "en", fx.slug(event))
    assert (found is not None) is (name in PUBLIC)
    if found is not None:
        assert found[0].id == event.id and found[1].locale == "en"


async def test_event_by_slug_needs_a_text_in_that_locale(db):
    fx = await seed_public_fixture(db)
    assert await read.event_by_slug(db, "de", fx.slug(fx.one_off, "de")) is not None
    assert await read.event_by_slug(db, "de", fx.slug(fx.conf)) is None
    assert await read.event_by_slug(db, "en", fx.slug(fx.one_off, "de")) is None


async def _redirect(db, event, locale, old):
    db.add(Redirect(event_id=event.id, locale=locale, old_slug=old))
    await db.flush()


async def test_event_redirect_through_gate(db):
    fx = await seed_public_fixture(db)
    await _redirect(db, fx.one_off, "en", "old-one-off")
    await _redirect(db, fx.draft, "en", "old-draft")
    await _redirect(db, fx.internal_event, "en", "old-internal")
    await _redirect(db, fx.trashed, "en", "old-trashed")
    await _redirect(db, fx.one_off, "de", "old-de")
    assert await read.resolve_event_redirect(db, "en", "old-one-off") == fx.slug(fx.one_off)
    for old in ("old-draft", "old-internal", "old-trashed", "never-existed"):
        assert await read.resolve_event_redirect(db, "en", old) is None, old
    # Language-scoped: the de redirect is not seen in en, and en's is not seen in de.
    assert await read.resolve_event_redirect(db, "en", "old-de") is None
    assert await read.resolve_event_redirect(db, "de", "old-de") == fx.slug(fx.one_off, "de")
    assert await read.resolve_event_redirect(db, "de", "old-one-off") is None


async def test_redirect_needs_a_text_in_the_locale(db):
    fx = await seed_public_fixture(db)
    await _redirect(db, fx.conf, "de", "old-conf")  # conf has no German text
    assert await read.resolve_event_redirect(db, "de", "old-conf") is None


async def test_redirect_onto_itself_is_none(db):
    fx = await seed_public_fixture(db)
    await _redirect(db, fx.one_off, "en", fx.slug(fx.one_off))
    assert await read.resolve_event_redirect(db, "en", fx.slug(fx.one_off)) is None


async def test_calendar_by_slug(db):
    fx = await seed_public_fixture(db)
    got = await read.calendar_by_slug(db, fx.pub.slug)
    assert got is not None and got.id == fx.pub.id
    for hidden in (fx.internal, fx.private, fx.gone):
        assert await read.calendar_by_slug(db, hidden.slug) is None, hidden.slug
    assert await read.calendar_by_slug(db, "nope") is None


async def test_children(db):
    fx = await seed_public_fixture(db)
    assert [e.id for e in await read.public_children(db, fx.conf.id)] == [fx.talk.id]
    # A parent that is not public lists nothing, though its child is public on its own.
    assert await read.public_children(db, fx.draft_parent.id) == []
    assert await read.public_parent(db, fx.orphan) is None
    parent = await read.public_parent(db, fx.talk)
    assert parent is not None and parent.id == fx.conf.id
    assert await read.public_parent(db, fx.one_off) is None


async def test_public_texts_only_for_public_events(db):
    fx = await seed_public_fixture(db)
    wanted = [e.id for e in (*fx.public_events, *fx.hidden.values())]
    texts = await read.public_texts(db, wanted)
    assert set(texts) == {e.id for e in fx.public_events}
    assert set(texts[fx.one_off.id]) == {"en", "de"}
    assert await read.public_texts(db, []) == {}


async def test_categories_only_from_public_events(db):
    fx = await seed_public_fixture(db)
    assert [c.id for c in await read.public_categories(db)] == [fx.public_cat.id]
    assert (await read.category_by_slug(db, fx.public_cat.slug)) is not None
    assert await read.category_by_slug(db, fx.draft_cat.slug) is None
    assert await read.category_by_slug(db, "nope") is None


def _text(locale: str) -> EventText:
    return EventText(event_id=None, locale=locale, slug=locale, title=locale)  # type: ignore[arg-type]


def test_pick_text_fallback():
    texts = {"de": _text("de"), "en": _text("en")}
    assert read.pick_text(texts, "de", "en").locale == "de"
    assert read.pick_text({"en": _text("en")}, "de", "en").locale == "en"
    # Neither the visitor's nor the default language: the first by tag.
    assert read.pick_text({"fr": _text("fr"), "de": _text("de")}, "it", "en").locale == "de"
    assert read.pick_text({"de": _text("de")}, "en", "en").locale == "de"


@pytest.mark.unbound_tenant
async def test_other_tenant(db):
    with tenant_scope("b"):
        other = await seed_public_fixture(db, tag="-b")
    with tenant_scope("a"):
        mine = await seed_public_fixture(db, tag="-a")
        await _assert_only(db, mine, other)


async def _assert_only(db, mine: PublicFixture, other: PublicFixture) -> None:
    for event in (*other.public_events,):
        assert await read.event_by_slug(db, "en", other.slug(event)) is None
    assert await read.calendar_by_slug(db, other.pub.slug) is None
    assert await read.public_children(db, other.conf.id) == []
    assert await read.public_parent(db, other.talk) is None
    assert await read.public_texts(db, [e.id for e in other.public_events]) == {}
    assert {c.id for c in await read.public_categories(db)} == {mine.public_cat.id}
    db.add(Redirect(event_id=other.one_off.id, locale="en", old_slug="x-old"))
    # (a redirect row of tenant a pointing at b's event is a foreign row: still nothing)
    await db.flush()
    assert await read.resolve_event_redirect(db, "en", "x-old") is None
    # Our own is still found.
    assert await read.event_by_slug(db, "en", mine.slug(mine.one_off)) is not None
    count = select(func.count()).select_from(Calendar).where(Calendar.slug == other.pub.slug)
    assert await db.scalar(count) == 0
