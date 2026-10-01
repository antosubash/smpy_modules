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

from tests.app_harness import ADMIN, roles
from tests.i18n_helpers import API, TYPE_KEY, make_record, make_type, publish, translate
from tests.i18n_helpers import use_locales as _use_locales

PREFIX = "/api/records/public"


@pytest_asyncio.fixture
async def site(client):
    """A two-language install with the public router mounted, as the host's
    own ``on_startup`` mounts it (its prefix is a DB-backed setting)."""
    _use_locales(client, "en", "de")
    await client.app.state.records_module.on_startup(client.app)
    await make_type(client, is_public=True)
    return client


async def _published_pair(site, title: str = "About us") -> tuple[dict, dict]:
    """An English record and its published German sibling, sharing a group."""
    english = await publish(site, await make_record(site, title))
    german = (await translate(site, english["uuid"], "de")).json()
    return english, await publish(site, german)


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


async def test_the_page_resolves_siblings_in_one_query_not_one_per_row(site):
    """§9's rule, applied to the language switcher: one batched query per
    page, keyed by ``translation_group``. A per-row query here is the
    difference between a public listing and fifty round trips."""
    for title in ("One", "Two", "Three", "Four"):
        english = await publish(site, await make_record(site, title))
        await publish(site, (await translate(site, english["uuid"], "de")).json())

    seen: list[str] = []

    def record(conn, cursor, statement, *args):
        if "translation_group IN" in statement:
            seen.append(statement)

    engine = site.db_state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        page = await site.get(f"{PREFIX}/{TYPE_KEY}")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(page.json()["items"]) == 4
    assert all(len(item["translations"]) == 2 for item in page.json()["items"])
    assert len(seen) == 1, f"{len(seen)} sibling queries for a page of 4"


async def test_a_private_type_is_still_a_404_in_every_language(site):
    await make_type(site, is_public=False, key="memo")
    for url in (f"{PREFIX}/memo", f"{PREFIX}/memo?locale=de"):
        assert (await site.get(url)).status_code == 404


async def _export(client, fmt: str) -> str:
    resp = await client.get(f"{API}/{TYPE_KEY}/records/export?format={fmt}", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return resp.text


async def _import(client, text: str, fmt: str, **params):
    return await client.post(
        f"{API}/{TYPE_KEY}/records/import",
        content=text.encode(),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
        params={"format": fmt, "dry_run": "false", **params},
    )


async def test_the_export_carries_locale_and_group_and_reimports_as_a_no_op(site):
    english, german = await _published_pair(site)
    document = json.loads(await _export(site, "json"))
    by_uuid = {row["uuid"]: row for row in document["records"]}
    assert by_uuid[english["uuid"]]["locale"] == "en"
    assert by_uuid[german["uuid"]]["locale"] == "de"
    assert (
        by_uuid[english["uuid"]]["translation_group"]
        == by_uuid[german["uuid"]]["translation_group"]
    )

    again = await _import(site, json.dumps(document), "json")
    assert again.status_code == 200, again.text
    assert again.json()["skipped"] == 2
    assert again.json()["created"] == again.json()["updated"] == 0


async def test_an_import_creates_records_in_the_locale_and_group_the_file_names(site):
    """The two groups a row may name: its own uuid, or one the file describes.

    A ``translation_group`` is a uniqueness exemption, so a row naming a group
    that exists in the database but not in the file is refused rather than
    honoured — see ``_import_plan._forged_group`` and
    ``test_import_groups.py`` for the exemption that closes.
    """
    english, _ = await _published_pair(site)
    document = {
        "records": [
            {
                "uuid": "f" * 32,
                "slug": "presse",
                "locale": "de",
                "translation_group": english["translation_group"],
                "status": "draft",
                "data": {"title": "Presse", "body": "…"},
            }
        ]
    }
    forged = await _import(site, json.dumps(document), "json")
    assert forged.status_code == 422, forged.text
    assert "names a group not in this file" in forged.text

    # Its own uuid: a record alone in a group named after itself.
    document["records"][0]["translation_group"] = "f" * 32
    ok = await _import(site, json.dumps(document), "json")
    assert ok.status_code == 200, ok.text
    assert ok.json()["created"] == 1
    written = await site.get(f"{API}/{TYPE_KEY}/records/{'f' * 32}", headers=roles(ADMIN))
    assert written.json()["locale"] == "de"
    assert written.json()["translation_group"] == "f" * 32


async def test_two_rows_of_one_file_sharing_a_group_and_a_language_still_collide(site):
    """The pair rule is not a way round ``(type, group, locale)``.

    Two rows carrying one group travel together legitimately — that is what an
    export of a translated pair is — but they must still be in *different*
    languages, and the unique index is what says so.
    """
    document = {
        "records": [
            {
                "uuid": "d" * 32,
                "locale": "de",
                "translation_group": "e" * 32,
                "data": {"title": "Eins", "body": "…"},
            },
            {
                "uuid": "e" * 32,
                "locale": "de",
                "translation_group": "e" * 32,
                "data": {"title": "Zwei", "body": "…"},
            },
        ]
    }
    clash = await _import(site, json.dumps(document), "json")
    assert clash.status_code == 422, clash.text
    assert "translation group" in clash.text


async def test_an_import_defaults_a_missing_locale_and_refuses_an_unknown_one(site):
    """A file written before this install spoke more than one language is a
    file of default-locale records; a named locale that is not configured is
    that row's error, not a reason to abort the parse."""
    plain = {"records": [{"uuid": "1" * 32, "data": {"title": "Nine", "body": "…"}}]}
    ok = await _import(site, json.dumps(plain), "json")
    assert ok.status_code == 200, ok.text
    written = await site.get(f"{API}/{TYPE_KEY}/records/{'1' * 32}", headers=roles(ADMIN))
    assert written.json()["locale"] == "en"
    # No group column either: alone in a group named after its own uuid.
    assert written.json()["translation_group"] == "1" * 32

    bad = {"records": [{"uuid": "2" * 32, "locale": "fr", "data": {"title": "Dix", "body": "…"}}]}
    refused = await _import(site, json.dumps(bad), "json")
    assert refused.status_code == 422, refused.text
    assert "'fr'" in refused.text


async def test_an_import_cannot_move_a_record_between_languages(site):
    english, _ = await _published_pair(site)
    document = json.loads(await _export(site, "json"))
    for row in document["records"]:
        if row["uuid"] == english["uuid"]:
            row["locale"] = "de"
    refused = await _import(site, json.dumps(document), "json")
    assert refused.status_code == 422, refused.text
    assert "fixed for its lifetime" in refused.text
