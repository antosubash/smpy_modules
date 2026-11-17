"""Names and free text reject control characters, at the schema and over HTTP."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_events.web.schemas.calendars import CalendarCreate, CalendarPatch
from sm_events.web.schemas.categories import CategoryCreate, CategoryPatch

from tests.support.calendars import BASE, OWNER, make
from tests.web.test_categories_api import BASE as CATS
from tests.web.test_categories_api import MANAGER

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
