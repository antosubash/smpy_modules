"""Two import rules the planning pass owns: which group a row may join, and
which rows need a ``version``.

Both were found by QA in the same shape — a rule the write path enforced and
the planning pass did not — and both are fixed the same way, by moving the
question into ``_import_checks`` where a dry run can ask it.

**Groups.** A ``translation_group`` is not data, it is a capability: records
sharing one are exempt from each other's ``unique`` claims (§5 / §4.3). §2 has
the importer carry it verbatim, so a hand-written row naming an existing
record's group bought that exemption — two records holding one ``unique``
value, for the price of ``records.edit`` and a second content locale.

**Versions.** The export carries no ``version``, so a row that would *update*
a record has to supply one or say ``force``. That refusal lived in
``write_row``, which a dry run never reaches: the preview said "1 to update, 0
failed" and the apply then failed the row.
"""

from __future__ import annotations

import json

import pytest_asyncio

from tests.app_harness import ADMIN, api_record, api_type, roles
from tests.i18n_helpers import field
from tests.i18n_helpers import use_locales as _use_locales

API = "/api/records/types"


async def _type(client, key: str, **cols):
    fields = [field("title", "text"), {**field("sku", "text"), "unique": True}]
    return await api_type(
        client, key, fields, display_field="title", slug_field="title", translatable=True, **cols
    )


async def _import(client, key: str, rows: list[dict], **params):
    query = "&".join(f"{name}={value}" for name, value in {"dry_run": "false", **params}.items())
    return await client.post(
        f"{API}/{key}/records/import?{query}",
        content=json.dumps({"records": rows}).encode(),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )


@pytest_asyncio.fixture
async def site(client):
    _use_locales(client, "en", "de")
    return client


async def test_a_forged_group_cannot_buy_the_unique_exemption(site):
    """The finding, in its original shape: an unrelated German record claiming
    the English record's group so it may repeat its ``unique`` SKU."""
    await _type(site, "art")
    original = await api_record(site, "art", {"title": "One", "sku": "SKU1"})

    refused = await _import(
        site,
        "art",
        [
            {
                "data": {"title": "Impostor", "sku": "SKU1"},
                "locale": "de",
                "translation_group": original["translation_group"],
            }
        ],
    )
    assert refused.status_code == 422, refused.text
    report = refused.json()["report"]
    assert report["created"] == 0
    assert "names a group not in this file" in report["errors"][0]["message"]
    assert "translations" in report["errors"][0]["message"]

    listed = await site.get(f"{API}/art/records?filter=sku:eq:SKU1", headers=roles(ADMIN))
    assert [item["uuid"] for item in listed.json()["items"]] == [original["uuid"]]


async def test_the_dry_run_predicts_the_group_refusal(site):
    await _type(site, "art")
    original = await api_record(site, "art", {"title": "One", "sku": "SKU1"})
    preview = await _import(
        site,
        "art",
        [
            {
                "data": {"title": "Impostor", "sku": "SKU2"},
                "locale": "de",
                "translation_group": original["translation_group"],
            }
        ],
        dry_run="true",
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["created"] == 0
    assert preview.json()["failed"] == 1


async def test_a_row_may_name_its_own_uuid_as_its_group(site):
    await _type(site, "art")
    report = await _import(
        site,
        "art",
        [{"uuid": "a" * 32, "translation_group": "a" * 32, "data": {"title": "Solo", "sku": "S"}}],
    )
    assert report.status_code == 200, report.text
    assert report.json()["created"] == 1


async def test_a_translated_pair_travelling_together_is_accepted(site):
    """What a legitimate export of a group looks like: every member present."""
    await _type(site, "art")
    made = await _import(
        site,
        "art",
        [
            {
                "uuid": "a" * 32,
                "locale": "en",
                "translation_group": "a" * 32,
                "data": {"title": "One", "sku": "SKU9"},
            },
            {
                "uuid": "b" * 32,
                "locale": "de",
                "translation_group": "a" * 32,
                "data": {"title": "Eins", "sku": "SKU9"},
            },
        ],
    )
    assert made.status_code == 200, made.text
    assert made.json()["created"] == 2

    panel = await site.get(f"{API}/art/records/{'a' * 32}/translations", headers=roles(ADMIN))
    assert sorted(row["locale"] for row in panel.json()) == ["de", "en"]


async def test_a_round_trip_of_a_translated_pair_is_still_a_no_op(site):
    """The whole group is in the file, so re-importing an export converges."""
    await _type(site, "art")
    english = await api_record(site, "art", {"title": "One", "sku": "SKU1"})
    german = await site.post(
        f"{API}/art/records/{english['uuid']}/translations",
        json={"locale": "de"},
        headers=roles(ADMIN),
    )
    assert german.status_code == 201, german.text

    export = await site.get(f"{API}/art/records/export?format=json", headers=roles(ADMIN))
    again = await _import(site, "art", json.loads(export.text)["records"])
    assert again.status_code == 200, again.text
    assert again.json()["skipped"] == 2
    assert again.json()["failed"] == 0


async def test_another_types_group_is_simply_a_group_this_type_lacks(site):
    """Groups are scoped by type everywhere that reads one, and since
    ``fe3ea2dfe0fb`` the unique index agrees — so this is not a collision and
    not a forgery, and the refusal that used to name a nonexistent record of
    the other type is gone."""
    await _type(site, "art")
    await _type(site, "memo")
    original = await api_record(site, "art", {"title": "One", "sku": "S1"})

    made = await _import(
        site,
        "memo",
        [
            {
                "data": {"title": "Unrelated", "sku": "S9"},
                "locale": "en",
                "translation_group": original["translation_group"],
            }
        ],
    )
    assert made.status_code == 200, made.text
    assert made.json()["created"] == 1


async def test_the_dry_run_predicts_a_missing_version(site):
    """Export, change one value, preview: the row is reported as failed with
    the version message rather than promised as an update."""
    await _type(site, "art")
    await api_record(site, "art", {"title": "One", "sku": "S1"})
    export = await site.get(f"{API}/art/records/export?format=json", headers=roles(ADMIN))
    rows = json.loads(export.text)["records"]
    rows[0]["data"]["title"] = "Changed"

    preview = await _import(site, "art", rows, dry_run="true")
    assert preview.status_code == 200, preview.text
    assert preview.json()["updated"] == 0
    assert preview.json()["failed"] == 1
    error = preview.json()["errors"][0]
    assert error["row"] == 1
    assert error["field"] == "version"
    assert "carries no 'version'" in error["message"]

    applied = await _import(site, "art", rows)
    assert applied.status_code == 422, applied.text
    assert applied.json()["report"]["errors"][0]["row"] == 1


async def test_force_plans_it_as_an_update_and_applies_it(site):
    await _type(site, "art")
    made = await api_record(site, "art", {"title": "One", "sku": "S1"})
    export = await site.get(f"{API}/art/records/export?format=json", headers=roles(ADMIN))
    rows = json.loads(export.text)["records"]
    rows[0]["data"]["title"] = "Changed"

    preview = await _import(site, "art", rows, dry_run="true", force="true")
    assert preview.status_code == 200, preview.text
    assert preview.json()["updated"] == 1
    assert preview.json()["failed"] == 0

    applied = await _import(site, "art", rows, force="true")
    assert applied.status_code == 200, applied.text
    assert applied.json()["updated"] == 1
    after = await site.get(f"{API}/art/records/{made['uuid']}", headers=roles(ADMIN))
    assert after.json()["data"]["title"] == "Changed"


async def test_an_abort_failure_during_the_write_names_its_row(site):
    """``on_error=abort`` used to report every write-time failure as row 0.

    Row 1 writes and claims the slug; row 2 collides with it inside the write
    pass, which is the one failure the planning pass cannot see (the slug is
    derived from the payload and neither row exists yet).
    """
    await _type(site, "art")
    refused = await _import(
        site,
        "art",
        [
            {"data": {"title": "Dup", "sku": "S1"}},
            {"data": {"title": "Dup", "sku": "S2"}},
        ],
    )
    assert refused.status_code == 422, refused.text
    error = refused.json()["report"]["errors"][0]
    assert error["row"] == 2, "the failing row, not the placeholder 0"
    assert "slug" in error["message"]
