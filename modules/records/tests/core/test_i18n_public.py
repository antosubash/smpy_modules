"""The anonymous read API in more than one language (§4.4), and the files.

Two things are being defended here.

The first is the original design's own acceptance test, stated as a warning
rather than a feature: **a ``de`` record must never be served for the ``en``
slug.** ``?locale=`` absent means the default content locale and never "all",
because an anonymous reader is asking for one site.

The second is that an export can be imported back. A file that lost ``locale``
and ``translation_group`` would collapse every record into the default
language and break every group apart — silently, and only on the install that
had more than one language to lose.
"""

from __future__ import annotations

import json

import pytest_asyncio
from sqlalchemy import event

from tests.support.app_harness import ADMIN, roles
from tests.support.i18n_helpers import API, TYPE_KEY, make_record, make_type, publish, translate
from tests.support.i18n_helpers import use_locales as _use_locales

from tests.support.i18n_public_cases import site, _published_pair, _export, _import, PREFIX


async def test_a_german_record_is_never_served_for_the_english_slug(site):
    """The acceptance test of the original design's §12 warning.

    The same word is the address in both languages — that is what scoping the
    unique index to the locale buys — and asking for one must never return the
    other.
    """
    english, german = await _published_pair(site)
    assert english["slug"] == german["slug"] == "about-us"

    default = await site.get(f"{PREFIX}/{TYPE_KEY}?filter=slug:eq:about-us")
    assert [item["uuid"] for item in default.json()["items"]] == [english["uuid"]]
    assert default.json()["items"][0]["locale"] == "en"

    asked = await site.get(f"{PREFIX}/{TYPE_KEY}?locale=de&filter=slug:eq:about-us")
    assert [item["uuid"] for item in asked.json()["items"]] == [german["uuid"]]


async def test_no_locale_means_the_default_one_and_never_all(site):
    await _published_pair(site)
    await publish(site, await make_record(site, "Kontakt", locale="de"))

    default = await site.get(f"{PREFIX}/{TYPE_KEY}")
    assert {item["locale"] for item in default.json()["items"]} == {"en"}
    assert default.json()["total"] == 1

    german = await site.get(f"{PREFIX}/{TYPE_KEY}?locale=de")
    assert {item["locale"] for item in german.json()["items"]} == {"de"}
    assert german.json()["total"] == 2


async def test_the_total_is_narrowed_to_the_locale_too(site):
    """Both halves of the bounded count take the same predicate the page does,
    or a listing reports rows it will not show."""
    await _published_pair(site)
    for title in ("Kontakt", "Impressum", "Presse"):
        await publish(site, await make_record(site, title, locale="de"))
    page = await site.get(f"{PREFIX}/{TYPE_KEY}?locale=de&page_size=2")
    assert page.json()["total"] == 4
    assert len(page.json()["items"]) == 2


async def test_an_unknown_locale_is_a_400_naming_it(site):
    """Not the flat "cannot filter or sort by" a refused field gets: this is a
    parameter of this route, and telling a caller which languages the site
    publishes in is its front door, not an oracle over private content."""
    resp = await site.get(f"{PREFIX}/{TYPE_KEY}?locale=fr")
    assert resp.status_code == 400, resp.text
    assert "'fr'" in resp.text
    assert "en, de" in resp.text


async def test_locale_is_not_a_filter_an_anonymous_caller_may_write(site):
    """``locale`` is a fixed column the public *shape* publishes, but the
    grammar answers only about ``slug``/``display_title``/``published_at`` —
    ``?locale=`` is the parameter, and a raw filter is refused like any column
    outside the public projection."""
    await _published_pair(site)
    resp = await site.get(f"{PREFIX}/{TYPE_KEY}?filter=locale:eq:de")
    assert resp.status_code == 400, resp.text


async def test_the_by_uuid_read_is_locale_blind(site):
    """A uuid names exactly one record, in exactly one language."""
    _, german = await _published_pair(site)
    plain = await site.get(f"{PREFIX}/{TYPE_KEY}/{german['uuid']}")
    assert plain.status_code == 200
    assert plain.json()["locale"] == "de"
    # ``?locale=`` is not a parameter here and is ignored, not honoured.
    ignored = await site.get(f"{PREFIX}/{TYPE_KEY}/{german['uuid']}?locale=en")
    assert ignored.status_code == 200
    assert ignored.json()["uuid"] == german["uuid"]


async def test_translations_list_only_published_live_siblings(site):
    english, german = await _published_pair(site)
    one = await site.get(f"{PREFIX}/{TYPE_KEY}/{english['uuid']}")
    assert {item["locale"] for item in one.json()["translations"]} == {"en", "de"}
    assert {item["slug"] for item in one.json()["translations"]} == {"about-us"}
    # No ``translation_group`` on the wire: an internal join key, not an
    # address a reader could do anything with.
    assert "translation_group" not in one.json()

    # A draft sibling is not advertised — following it would be a 404.
    draft_src = await publish(site, await make_record(site, "Contact"))
    await translate(site, draft_src["uuid"], "de")
    contact = await site.get(f"{PREFIX}/{TYPE_KEY}/{draft_src['uuid']}")
    assert [item["locale"] for item in contact.json()["translations"]] == ["en"]

    # Nor is a trashed one.
    await site.delete(f"{API}/{TYPE_KEY}/records/{german['uuid']}", headers=roles(ADMIN))
    after = await site.get(f"{PREFIX}/{TYPE_KEY}/{english['uuid']}")
    assert [item["locale"] for item in after.json()["translations"]] == ["en"]
