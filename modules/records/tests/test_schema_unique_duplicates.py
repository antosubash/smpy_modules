"""Turning ``unique`` on over records that already hold duplicates.

``schema/diff`` classifies ``unique_added`` as **restrictive**, and
``docs/architecture.md`` states what restrictive means: "only after a clean
dry run, or under ``force``". The dry run, though, validates one record's
payload at a time against the proposed model, and duplication is a property of
a *pair* — so the guard ran, said ``failing: 0, clean: true``, and the change
applied. Both records were then permanently unsaveable: every write to either
was a 409 from ``_claims.ensure_unique``, including a write that did not touch
the duplicated field at all.

Two halves to the fix and so two halves to this file: the preview must see the
duplicates and the ``PUT`` must refuse without ``force``; and under ``force``
the records must be *marked* like every other restrictive failure and must
stay saveable for any write that leaves the contested value alone.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles
from tests.i18n_helpers import use_locales

API = "/api/records/types/product"


def _field(key: str, type_: str, *, unique: bool = False, indexed: bool = True, **options) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": False,
        "unique": unique,
        "indexed": indexed,
        "default": None,
        "help": None,
        "constraints": {},
        "options": options,
    }


async def _type(client, *, sku_indexed: bool = True, **cols) -> dict:
    body = {
        "key": "product",
        "label": "Product",
        "fields": [_field("name", "text"), _field("sku", "text", indexed=sku_indexed)],
        "display_field": "name",
        **cols,
    }
    resp = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert resp.status_code == 201
    return resp.json()


async def _record(client, name: str, sku: str) -> dict:
    resp = await client.post(
        f"{API}/records", json={"data": {"name": name, "sku": sku}}, headers=roles(ADMIN)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _unique_sku(rtype: dict) -> list[dict]:
    return [{**f, "unique": True} if f["key"] == "sku" else f for f in rtype["fields"]]


async def test_the_preview_reports_the_duplicates_and_the_put_is_refused(client):
    rtype = await _type(client)
    first = await _record(client, "A", "SKU-1")
    second = await _record(client, "B", "SKU-1")
    await _record(client, "C", "SKU-2")

    preview = await client.post(
        f"{API}/schema/preview", json={"fields": _unique_sku(rtype)}, headers=roles(ADMIN)
    )
    assert preview.status_code == 200
    report = preview.json()["report"]
    assert preview.json()["kind"] == "restrictive"
    assert report["checked"] == 3
    assert report["failing"] == 2
    assert report["duplicates"] == {"sku": 2}
    assert report["clean"] is False
    assert {entry["uuid"] for entry in report["sample"]} == {first["uuid"], second["uuid"]}
    assert "SKU-1" in report["sample"][0]["errors"][0]["message"]

    refused = await client.put(
        API,
        json={"expected_version": rtype["version"], "fields": _unique_sku(rtype)},
        headers=roles(ADMIN),
    )
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["report"]["duplicates"] == {"sku": 2}
    assert "cannot be fixed by editing the record" in body["detail"]

    # Nothing was written: the field is still not unique.
    stored = await client.get(API, headers=roles(ADMIN))
    assert [f["unique"] for f in stored.json()["fields"] if f["key"] == "sku"] == [False]


async def test_a_field_not_yet_indexed_is_scanned_on_the_walk_instead(client):
    """``unique`` normalises to imply ``indexed``, so a field gaining both at
    once has no index rows to ``GROUP BY``. The duplicate collector rides on
    the payload pass the dry run is already making."""
    rtype = await _type(client, sku_indexed=False)
    await _record(client, "A", "SKU-1")
    await _record(client, "B", "SKU-1")

    preview = await client.post(
        f"{API}/schema/preview", json={"fields": _unique_sku(rtype)}, headers=roles(ADMIN)
    )
    report = preview.json()["report"]
    assert report["duplicates"] == {"sku": 2}
    assert report["failing"] == 2


async def test_translation_siblings_are_not_duplicates_of_each_other(client):
    """``ensure_unique`` exempts records sharing a ``translation_group``
    (Phase 5 §4.3), so the scan must too — otherwise a translated type could
    never gain a unique field."""
    use_locales(client, "en", "de")
    rtype = await _type(client, translatable=True)
    source = await _record(client, "A", "SKU-1")
    sibling = await client.post(
        f"{API}/records/{source['uuid']}/translations",
        json={"locale": "de"},
        headers=roles(ADMIN),
    )
    assert sibling.status_code == 201, sibling.text

    preview = await client.post(
        f"{API}/schema/preview", json={"fields": _unique_sku(rtype)}, headers=roles(ADMIN)
    )
    report = preview.json()["report"]
    assert report["duplicates"] == {}
    assert report["clean"] is True


async def test_under_force_the_records_are_marked_and_stay_saveable(client):
    rtype = await _type(client)
    first = await _record(client, "A", "SKU-1")
    second = await _record(client, "B", "SKU-1")

    forced = await client.put(
        API,
        json={
            "expected_version": rtype["version"],
            "fields": _unique_sku(rtype),
            "force": True,
        },
        headers=roles(ADMIN),
    )
    assert forced.status_code == 200, forced.text
    assert [f["unique"] for f in forced.json()["fields"] if f["key"] == "sku"] == [True]

    # Marked: the single-record read carries the badge §8.3 promises, even
    # though this record's own payload validates perfectly.
    read = await client.get(f"{API}/records/{first['uuid']}", headers=roles(ADMIN))
    assert read.status_code == 200
    assert [entry["field"] for entry in read.json()["invalid"]] == ["sku"]
    assert "SKU-1" in read.json()["invalid"][0]["message"]

    # Saveable: a write that leaves the contested value alone is not a new
    # claim and is not refused.
    saved = await client.put(
        f"{API}/records/{first['uuid']}",
        json={
            "expected_version": read.json()["version"],
            "data": {"name": "A renamed", "sku": "SKU-1"},
        },
        headers=roles(ADMIN),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["name"] == "A renamed"

    # …and the rule still holds for a claim that *is* new: a third record
    # cannot take the value, and neither record may move to the other's.
    third = await client.post(
        f"{API}/records", json={"data": {"name": "C", "sku": "SKU-1"}}, headers=roles(ADMIN)
    )
    assert third.status_code == 409

    # Editing one of them *out* of the duplicate clears the badge for it.
    fixed = await client.put(
        f"{API}/records/{second['uuid']}",
        json={"expected_version": second["version"], "data": {"name": "B", "sku": "SKU-2"}},
        headers=roles(ADMIN),
    )
    assert fixed.status_code == 200, fixed.text
    again = await client.get(f"{API}/records/{first['uuid']}", headers=roles(ADMIN))
    assert again.json()["invalid"] == []
