"""Texts per locale: defaults, slugs, redirects and the sanitiser at save."""

from __future__ import annotations

import pytest
from sm_events.calendar import slugs
from sm_events.content.texts import apply_texts, texts_of
from sm_events.core.errors import DefaultLocaleRequired, SlugTaken, UnknownLocale
from sm_events.models import Calendar, Redirect
from sm_events.web.schemas.texts import TextIn
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.calendars import bare_event

LOCALES = ("en", "de")


def t(title: str = "Concert", **kw) -> TextIn:
    return TextIn(title=title, **kw)


async def new_event(db, texts, *, locales=LOCALES):
    cal = (await seed_calendars(db))["I"]
    event = await bare_event(db, cal)
    await apply_texts(db, event, texts, locales=locales, creating=True)
    return event


async def redirects(db):
    rows = (await db.execute(select(Redirect))).scalars().all()
    return sorted((r.locale, r.old_slug) for r in rows)


async def test_default_locale_required_on_create(db):
    cal = (await seed_calendars(db))["I"]
    event = await bare_event(db, cal)
    with pytest.raises(DefaultLocaleRequired):
        await apply_texts(db, event, {"de": t()}, locales=LOCALES, creating=True)
    with pytest.raises(DefaultLocaleRequired):
        await apply_texts(db, event, {"en": None}, locales=LOCALES, creating=True)


async def test_null_deletes_but_never_default(db):
    event = await new_event(db, {"en": t(), "de": t("Konzert")})
    with pytest.raises(DefaultLocaleRequired):
        await apply_texts(db, event, {"en": None}, locales=LOCALES, creating=False)
    changed = await apply_texts(db, event, {"de": None}, locales=LOCALES, creating=False)
    assert changed == ["de"]
    await db.flush()
    assert set((await texts_of(db, [event.id]))[event.id]) == {"en"}


async def test_unknown_locale(db):
    cal = (await seed_calendars(db))["I"]
    event = await bare_event(db, cal)
    with pytest.raises(UnknownLocale):
        await apply_texts(db, event, {"en": t(), "fr": t()}, locales=LOCALES, creating=True)
    assert (await texts_of(db, [event.id]))[event.id] == {}


async def test_patch_leaves_other_locales_alone(db):
    event = await new_event(db, {"en": t("A"), "de": t("B")})
    await apply_texts(db, event, {"de": t("C")}, locales=LOCALES, creating=False)
    got = (await texts_of(db, [event.id]))[event.id]
    assert got["en"].title == "A" and got["de"].title == "C"


async def _cal(db, event):
    return await db.get(Calendar, event.calendar_id)


async def test_slug_derived_per_locale(db):
    first = await new_event(db, {"en": t("Konzert"), "de": t("Konzert")})
    second = await bare_event(db, await _cal(db, first))
    await apply_texts(
        db, second, {"en": t("Konzert"), "de": t("Konzert")}, locales=LOCALES, creating=True
    )
    third = await bare_event(db, await _cal(db, first))
    await apply_texts(
        db, third, {"de": t("Konzert"), "en": t("Other")}, locales=LOCALES, creating=True
    )
    got = await texts_of(db, [first.id, second.id, third.id])
    assert got[first.id]["de"].slug == "konzert" and got[first.id]["en"].slug == "konzert"
    assert got[second.id]["de"].slug == "konzert-2" and got[second.id]["en"].slug == "konzert-2"
    assert got[third.id]["de"].slug == "konzert-3" and got[third.id]["en"].slug == "other"


async def test_same_slug_in_two_locales_on_two_events_is_fine(db):
    a = await new_event(db, {"en": t("x", slug="same")})
    b = await bare_event(db, await _cal(db, a))
    await apply_texts(
        db,
        b,
        {"en": t("y", slug="other"), "de": t("y", slug="same")},
        locales=LOCALES,
        creating=True,
    )
    await db.flush()


async def test_explicit_slug_taken_409(db):
    a = await new_event(db, {"en": t("x", slug="taken")})
    b = await bare_event(db, await _cal(db, a))
    with pytest.raises(SlugTaken):
        await apply_texts(db, b, {"en": t("y", slug="taken")}, locales=LOCALES, creating=True)


async def test_explicit_slug_taken_by_trashed_event(db):
    a = await new_event(db, {"en": t("x", slug="gone")})
    await db.delete(a)  # soft delete: the text row and its slug stay
    await db.flush()
    b = await bare_event(db, await _cal(db, a))
    with pytest.raises(SlugTaken):
        await apply_texts(db, b, {"en": t("y", slug="gone")}, locales=LOCALES, creating=True)


async def test_rename_records_redirect_in_that_locale_only(db):
    event = await new_event(db, {"en": t("x", slug="en-1"), "de": t("x", slug="de-1")})
    await apply_texts(db, event, {"de": t("x", slug="de-2")}, locales=LOCALES, creating=False)
    assert await redirects(db) == [("de", "de-1")]


async def test_title_change_alone_keeps_slug(db):
    event = await new_event(db, {"en": t("First")})
    await apply_texts(db, event, {"en": t("Second")}, locales=LOCALES, creating=False)
    assert (await texts_of(db, [event.id]))[event.id]["en"].slug == "first"
    assert await redirects(db) == []


async def test_claim_releases_redirect(db):
    a = await new_event(db, {"de": t("x", slug="old"), "en": t("x")})
    await apply_texts(db, a, {"de": t("x", slug="new")}, locales=LOCALES, creating=False)
    assert await redirects(db) == [("de", "old")]
    b = await bare_event(db, await _cal(db, a))
    await apply_texts(
        db, b, {"en": t("b"), "de": t("b", slug="old")}, locales=LOCALES, creating=True
    )
    assert await redirects(db) == []


async def test_rename_back_removes_redirect(db):
    event = await new_event(db, {"en": t("x", slug="one")})
    await apply_texts(db, event, {"en": t("x", slug="two")}, locales=LOCALES, creating=False)
    assert await redirects(db) == [("en", "one")]
    await apply_texts(db, event, {"en": t("x", slug="one")}, locales=LOCALES, creating=False)
    assert await redirects(db) == [("en", "two")]


async def test_description_cleaned_on_save(db):
    event = await new_event(
        db, {"en": t("x", description='<p onclick="x()">hi</p><script>bad()</script><img src=x>')}
    )
    assert (await texts_of(db, [event.id]))[event.id]["en"].description == "<p>hi</p>"


async def test_slug_race_is_conflict(db, monkeypatch):
    a = await new_event(db, {"en": t("x", slug="raced")})
    b = await bare_event(db, await _cal(db, a))

    async def free(*_a, **_k):
        return False

    monkeypatch.setattr("sm_events.content.texts.text_slug_taken", free)
    with pytest.raises(SlugTaken):
        await apply_texts(db, b, {"en": t("y", slug="raced")}, locales=LOCALES, creating=True)
    # the savepoint was rolled back: the session still works
    assert await slugs.text_slug_taken(db, "en", "raced")
