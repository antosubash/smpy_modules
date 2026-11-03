"""test_i18n_public cases."""

from __future__ import annotations

import json

from sqlalchemy import event

from tests.support.app_harness import ADMIN, roles
from tests.support.i18n_helpers import API, TYPE_KEY, make_record, make_type, publish, translate
from tests.support.i18n_public_cases import PREFIX, _export, _import, _published_pair
from tests.support.i18n_public_cases import site as site


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
