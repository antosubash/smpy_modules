"""``unique`` meets translation: the rule is *uniqueness among non-siblings*.

``unique`` is type-level and locale-blind (design §7.8), and a translation is
a whole sibling record that starts as a **copy of its source's payload**
(Phase 5 §4.3). Those two sentences used to contradict each other: translating
a record of a type with a ``unique`` field was a flat ``409`` — the sibling
collided with the record it was copied from, and the only workaround was not
to declare the field unique.

The rule now is that records sharing a ``translation_group`` do not claim
against each other. A German product carries the English product's SKU because
it *is* that product. Everything else is unchanged, and most of this file is
about the "everything else": two records in one language still collide, and so
do two records in two languages that are not translations of one another —
the exemption is per **group**, not per locale.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event

from tests.app_harness import ADMIN, field, roles
from tests.io_helpers import drop_type, export_text, post_import

API = "/api/records/types"
TYPE_KEY = "product"


def type_fields() -> list[dict]:
    return [field("name"), field("sku", unique=True)]


async def make_type(client, key: str = TYPE_KEY, **cols: Any) -> dict:
    resp = await client.post(
        API,
        json={
            "key": key,
            "label": key.title(),
            "fields": cols.pop("fields", type_fields()),
            "display_field": "name",
            "slug_field": "name",
            "translatable": cols.pop("translatable", True),
            **cols,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def create(client, name: str, sku: str, *, key: str = TYPE_KEY, **body: Any):
    return await client.post(
        f"{API}/{key}/records",
        json={"data": {"name": name, "sku": sku}, **body},
        headers=roles(ADMIN),
    )


async def made(client, name: str, sku: str, **body: Any) -> dict:
    resp = await create(client, name, sku, **body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def translate(client, uuid: str, locale: str, **body: Any):
    return await client.post(
        f"{API}/{TYPE_KEY}/records/{uuid}/translations",
        json={"locale": locale, **body},
        headers=roles(ADMIN),
    )


async def translated(client, uuid: str, locale: str, **body: Any) -> dict:
    resp = await translate(client, uuid, locale, **body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def edit(client, record: dict, **data: Any):
    return await client.put(
        f"{API}/{TYPE_KEY}/records/{record['uuid']}",
        json={"expected_version": record["version"], "data": {**record["data"], **data}},
        headers=roles(ADMIN),
    )


async def trash(client, uuid: str) -> None:
    resp = await client.delete(f"{API}/{TYPE_KEY}/records/{uuid}", headers=roles(ADMIN))
    assert resp.status_code == 204, resp.text


async def test_a_translation_may_copy_a_unique_value(bilingual):
    """The bug this fixes: the sibling is created and keeps the SKU.

    Not "keeps a suffixed variant" and not "is created with the field
    cleared" — the payload is copied verbatim, because the two rows are the
    same product in two languages.
    """
    await make_type(bilingual)
    source = await made(bilingual, "Widget", "SKU-1")
    sibling = await translated(bilingual, source["uuid"], "de")

    assert sibling["data"]["sku"] == "SKU-1"
    assert sibling["locale"] == "de"
    assert sibling["translation_group"] == source["translation_group"]
    # Both rows hold the value at once; neither is the "real" one.
    reread = await bilingual.get(f"{API}/{TYPE_KEY}/records/{source['uuid']}", headers=roles(ADMIN))
    assert reread.json()["data"]["sku"] == "SKU-1"


async def test_two_records_in_one_locale_still_collide(bilingual):
    await make_type(bilingual)
    await made(bilingual, "Widget", "SKU-1")

    resp = await create(bilingual, "Other widget", "SKU-1")
    assert resp.status_code == 409, resp.text
    assert "'sku' must be unique" in resp.text


async def test_two_unrelated_records_in_different_locales_still_collide(bilingual):
    """**The exemption is per group, not per language.**

    This is the distinction the whole design turns on, and the one a reader
    is likeliest to get wrong: ``unique`` did not become "unique within a
    locale". Two records in two languages that are not translations of each
    other are two different products, and two products may not share a SKU —
    the German record below is written directly, not through
    ``POST /translations``, so it is alone in a group of its own.
    """
    await make_type(bilingual)
    source = await made(bilingual, "Widget", "SKU-1")

    resp = await create(bilingual, "Anderes Widget", "SKU-1", locale="de")
    assert resp.status_code == 409, resp.text
    assert "'sku' must be unique" in resp.text

    # …and the same value in the same language is fine through the seam that
    # *does* make them siblings, so the refusal above is about the group.
    sibling = await translated(bilingual, source["uuid"], "de")
    assert sibling["data"]["sku"] == "SKU-1"


async def test_a_trashed_sibling_does_not_block_its_group(bilingual):
    """Trash keeps a record's claims (§7.3) — but never against its own group.

    The sibling is still a sibling while it sits restorable, so the source can
    go on being edited with the value both of them hold. Anything else would
    make "delete the German copy" a reason the English record can no longer
    be saved.
    """
    await make_type(bilingual)
    source = await made(bilingual, "Widget", "SKU-1")
    sibling = await translated(bilingual, source["uuid"], "de")
    await trash(bilingual, sibling["uuid"])

    resp = await edit(bilingual, source, name="Widget mk2")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["sku"] == "SKU-1"


async def test_a_trashed_unrelated_record_still_blocks(bilingual):
    """The other half, unchanged from Phase 1: an unrelated record in the
    trash keeps its ``unique`` claim until it is purged, so a restore can
    never find its value taken."""
    await make_type(bilingual)
    first = await made(bilingual, "Widget", "SKU-1")
    await trash(bilingual, first["uuid"])

    resp = await create(bilingual, "Other widget", "SKU-1")
    assert resp.status_code == 409, resp.text
    assert "'sku' must be unique" in resp.text


async def test_editing_the_source_leaves_the_siblings_stale_copy_alone(bilingual):
    """A translation is a copy, not a mirror: nothing propagates between
    siblings, so the German row goes on holding a value the English row no
    longer has. It stays legal because they are still siblings — the
    exemption is the relationship, not the moment of copying — and the stale
    value still blocks everyone else.
    """
    await make_type(bilingual)
    source = await made(bilingual, "Widget", "SKU-1")
    sibling = await translated(bilingual, source["uuid"], "de")

    moved = await edit(bilingual, source, sku="SKU-2")
    assert moved.status_code == 200, moved.text
    assert (await edit(bilingual, sibling, name="Widget (de)")).status_code == 200

    # The sibling's copy is a real claim against the rest of the type.
    assert (await create(bilingual, "Third", "SKU-1")).status_code == 409


async def test_an_export_with_translated_unique_values_round_trips(bilingual):
    """A file describing a group whose rows share a ``unique`` value imports.

    The export carries ``translation_group``, the importer passes it to
    ``create_record``, and the second row is therefore exempt from the first
    — which is what makes an export of a translated catalogue a file that can
    be loaded back at all.
    """
    await make_type(bilingual)
    source = await made(bilingual, "Widget", "SKU-1")
    await translated(bilingual, source["uuid"], "de")
    document = await export_text(bilingual, TYPE_KEY)
    rows = json.loads(document)["records"]
    assert [row["data"]["sku"] for row in rows] == ["SKU-1", "SKU-1"]
    assert len({row["translation_group"] for row in rows}) == 1

    await drop_type(bilingual, TYPE_KEY, 2)
    await make_type(bilingual)
    report = await post_import(bilingual, TYPE_KEY, document, dry_run="false", mode="create")
    assert report.status_code == 200, report.text
    assert report.json()["created"] == 2, report.text

    listed = await bilingual.get(f"{API}/{TYPE_KEY}/records", headers=roles(ADMIN))
    items = listed.json()["items"]
    assert sorted(item["locale"] for item in items) == ["de", "en"]
    assert {item["data"]["sku"] for item in items} == {"SKU-1"}
    assert len({item["translation_group"] for item in items}) == 1


@contextmanager
def _statements(engine):
    """Every SQL statement the engine executes inside the block."""
    captured: list[str] = []
    sync_engine = getattr(engine, "sync_engine", engine)

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield captured
    finally:
        event.remove(sync_engine, "before_cursor_execute", _on_execute)


async def test_the_exemption_costs_a_plain_create_no_statements(bilingual):
    """The group is known before the write, so excluding it is a ``WHERE``
    clause on a query that was already being issued — never a lookup of its
    own. A create on a type with a ``unique`` field costs exactly one
    statement more than the same create without one (the existence check of
    §7.8), which is the 13/14 the perf suite pins.
    """
    await make_type(bilingual)
    await make_type(bilingual, "plain", fields=[field("name"), field("sku")])
    engine = bilingual.db_state.engine

    with _statements(engine) as plain:
        assert (await create(bilingual, "A", "PLAIN-1", key="plain")).status_code == 201
    with _statements(engine) as unique:
        assert (await create(bilingual, "A", "SKU-9")).status_code == 201

    assert len(unique) == len(plain) + 1, (plain, unique)
    checks = [sql for sql in unique if "records_index_text" in sql and "LIMIT" in sql]
    assert len(checks) == 1, checks
    # The exemption rides on that one statement rather than beside it.
    assert "translation_group" in checks[0]
