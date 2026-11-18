"""Names and free text reject control characters, at the schema and over HTTP."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_events.web.schemas.calendars import CalendarCreate, CalendarPatch
from sm_events.web.schemas.categories import CategoryCreate, CategoryPatch

from tests.support.calendars import BASE, OWNER, make
from tests.web.test_categories_api import BASE as CATS
from tests.web.test_categories_api import MANAGER

LINE_SEPARATORS = ["a\u2028b", "a\u2029b"]
BIDI = [
    f"a{c}b" for c in "\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
]
BAD = ["a\x00b", "a\nb", "a\tb", "a\rb", "a\x1fb", "a\x7fb", "a\x85b", "a\x9fb", "ok\n", "\x00"]


@pytest.mark.parametrize("bad", BAD)
def test_calendar_name_rejects_controls(bad):
    with pytest.raises(ValidationError):
        CalendarCreate(name=bad)
    with pytest.raises(ValidationError):
        CalendarPatch(name=bad)


@pytest.mark.parametrize("bad", BAD)
def test_category_names_reject_controls_in_every_locale(bad):
    with pytest.raises(ValidationError):
        CategoryCreate(names={"en": "Fine", "de": bad})
    with pytest.raises(ValidationError):
        CategoryPatch(names={"en": bad})


@pytest.mark.parametrize("bad", ["a\x00b", "a\x1bb", "a\x85b", "a\x7fb"])
def test_description_rejects_controls(bad):
    with pytest.raises(ValidationError):
        CalendarCreate(name="Team", description=bad)


def test_description_keeps_newlines_and_tabs():
    got = CalendarCreate(name="Team", description="line one\r\nline\ttwo\n")
    assert got.description == "line one\r\nline\ttwo\n"


def test_ordinary_names_still_pass():
    assert CalendarCreate(name="  Ärzte & Co - 日本語  ").name == "Ärzte & Co - 日本語"
    assert CategoryCreate(names={"en": "Musik 🎵"}).names == {"en": "Musik 🎵"}


@pytest.mark.parametrize("bad", ["a\u0000b", "a\nb"])
async def test_calendar_api_rejects_control_names(client, bad):
    got = await client.post(BASE, json={"name": bad}, headers=OWNER)
    assert got.status_code == 422, got.text
    made = await make(client, OWNER, name="Team")
    patched = await client.patch(f"{BASE}/{made['id']}", json={"name": bad}, headers=OWNER)
    assert patched.status_code == 422


async def test_calendar_api_rejects_nul_in_description_but_keeps_newlines(client):
    nul = await client.post(BASE, json={"name": "T", "description": "a\u0000b"}, headers=OWNER)
    assert nul.status_code == 422
    ok = await client.post(BASE, json={"name": "T", "description": "a\nb"}, headers=OWNER)
    assert ok.status_code == 201 and ok.json()["description"] == "a\nb"


@pytest.mark.parametrize("bad", ["a\u0000b", "a\nb"])
async def test_category_api_rejects_control_names(client, bad):
    got = await client.post(CATS, json={"names": {"en": bad}}, headers=MANAGER)
    assert got.status_code == 422, got.text


async def test_category_without_sluggable_name_gets_its_own_fallback(client):
    first = await client.post(CATS, json={"names": {"en": "😀"}}, headers=MANAGER)
    second = await client.post(CATS, json={"names": {"en": "שלום"}}, headers=MANAGER)
    assert [first.json()["slug"], second.json()["slug"]] == ["category", "category-2"]
    cal = await make(client, OWNER, name="😀")
    assert cal["slug"] == "calendar"


@pytest.mark.parametrize("bad", LINE_SEPARATORS + BIDI)
def test_single_line_names_reject_separators_and_direction_controls(bad):
    with pytest.raises(ValidationError):
        CalendarCreate(name=bad)
    with pytest.raises(ValidationError):
        CalendarPatch(name=bad)
    with pytest.raises(ValidationError):
        CategoryCreate(names={"en": "Fine", "de": bad})
    with pytest.raises(ValidationError):
        CategoryPatch(names={"en": bad})


@pytest.mark.parametrize("bad", BIDI)
def test_description_rejects_direction_controls(bad):
    with pytest.raises(ValidationError):
        CalendarCreate(name="Team", description=bad)


def test_description_may_keep_unicode_line_separators():
    got = CalendarCreate(name="Team", description="one\u2028two\u2029three")
    assert got.description == "one\u2028two\u2029three"


@pytest.mark.parametrize("bad", ["a\u2028b", "a\u202eb"])
async def test_api_rejects_separator_and_direction_names(client, bad):
    got = await client.post(BASE, json={"name": bad}, headers=OWNER)
    assert got.status_code == 422, got.text
    cat = await client.post(CATS, json={"names": {"en": bad}}, headers=MANAGER)
    assert cat.status_code == 422, cat.text
    desc = await client.post(BASE, json={"name": "T", "description": "a\u202eb"}, headers=OWNER)
    assert desc.status_code == 422, desc.text


@pytest.mark.parametrize("char", ["\u200b", "\u2060", "\ufeff"])
def test_single_line_rejects_invisible_spaces(char):
    with pytest.raises(ValidationError):
        CalendarCreate(name=f"a{char}b")
    with pytest.raises(ValidationError):
        CalendarCreate(name=char)


@pytest.mark.parametrize("char", ["\u200c", "\u200d"])
def test_single_line_keeps_the_joiners_scripts_need(char):
    assert CalendarCreate(name=f"می{char}خواهم").name == f"می{char}خواهم"
    assert CalendarCreate(name=f"👩{char}💻").name == f"👩{char}💻"


@pytest.mark.parametrize("char", ["​", "⁠", "﻿"])
def test_an_event_title_and_seo_title_reject_invisible_spaces(char):
    from sm_events.web.schemas.texts import TextIn

    with pytest.raises(ValidationError):
        TextIn(title=f"Con{char}cert")
    with pytest.raises(ValidationError):
        TextIn(title="Concert", seo_title=f"a{char}b")
