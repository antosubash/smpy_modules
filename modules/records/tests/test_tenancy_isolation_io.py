"""The isolation matrix, part 3: many records at once — K1.

Listing, filtering, sorting, counting, aggregating, exporting, importing,
bulk actions and emptying the trash, as ``globex``, under the type key both
tenants have. ``acme`` holds three ``post`` records (one of them trashed) and
a German sibling; ``globex`` holds two. Every answer here counts two, and
names neither of ``acme``'s rows.

``two_tenants`` checks on the way out that no ``acme`` row changed.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from tests.isolation_support import (
    ACME,
    ACME_ONLY,
    ACME_TRASHED,
    API,
    GLOBEX,
    GLOBEX_REF,
    INERTIA,
    NO_UUID,
    POST,
    SAME,
    VIEW,
    as_,
    covers,
    row,
    same_as_unknown,
)

pytestmark = pytest.mark.unbound_tenant

G = as_(GLOBEX)
RECORDS = f"{API}/{POST}/records"
MINE = {SAME, GLOBEX_REF}


def _uuids(page: dict) -> set[str]:
    return {item["uuid"] for item in page["items"]}


@covers("GET /api/records/types/{key}/records", "GET /admin/records/{key}")
@pytest.mark.parametrize(
    "query",
    [
        "",
        "?sort=-score",
        "?sort=title",
        "?filter=score:gte:0",
        "?filter=slug:eq:hello",
        f"?filter=link:eq:{SAME}",
        "?filter=title:eq:acme%20only",
        "?trashed=true",
        "?locale=de",
    ],
)
async def test_lists_filters_sorts_and_counts_only_the_callers_rows(two_tenants, query):
    page = (await two_tenants.get(RECORDS + query, headers=G)).json()
    screen = await two_tenants.get(f"{VIEW}/{POST}{query}", headers={**G, **INERTIA})
    props = screen.json()["props"]["records"]
    for listed in (page, props):
        assert _uuids(listed) <= MINE, query
        assert listed["total"] == len(listed["items"]), query
    assert _uuids(page) == _uuids(props)


async def test_the_list_counts_what_each_tenant_holds(two_tenants):
    assert (await two_tenants.get(RECORDS, headers=G)).json()["total"] == 2
    assert (await two_tenants.get(RECORDS, headers=as_(ACME))).json()["total"] == 3


@covers("GET /api/records/types/{key}/records/aggregate")
async def test_aggregates_fold_only_the_callers_rows(two_tenants):
    counted = await two_tenants.get(f"{RECORDS}/aggregate?group_by=status", headers=G)
    assert counted.status_code == 200, counted.text
    assert [(g["value"], g["count"]) for g in counted.json()["groups"]] == [("published", 2)]
    summed = await two_tenants.get(
        f"{RECORDS}/aggregate?group_by=status&metric=sum:score", headers=G
    )
    assert Decimal(summed.json()["groups"][0]["sum"]) == 4, "1 + 3; acme's would add 21"


@covers("GET /api/records/types/{key}/records/export")
@pytest.mark.parametrize("trashed", [False, True])
async def test_the_export_is_the_callers_rows_and_names_its_tenant(two_tenants, trashed):
    query = "?format=json" + ("&trashed=true" if trashed else "")
    exported = await two_tenants.get(f"{RECORDS}/export{query}", headers=G)
    assert exported.status_code == 200, exported.text
    document = exported.json()
    assert document["tenant"] == GLOBEX
    assert {r["uuid"] for r in document["records"]} == (set() if trashed else MINE)
    csv = await two_tenants.get(f"{RECORDS}/export?format=csv", headers=G)
    assert ACME_ONLY not in csv.text and "acme" not in csv.text
    assert "tenant" not in csv.text.splitlines()[0], "CSV is unchanged"


@covers("POST /api/records/types/{key}/records/import")
async def test_importing_another_tenants_uuid_is_importing_a_new_one(two_tenants):
    """No "uuid already in use" oracle: ``acme``'s uuid is free here, and the
    dry run says exactly what it says for a uuid nobody holds."""
    await same_as_unknown(
        two_tenants,
        "POST",
        f"{RECORDS}/import?dry_run=true",
        *({"uuid": uuid} for uuid in (ACME_ONLY, NO_UUID)),
        headers=G,
        body=lambda p: {"records": [row(p["uuid"], "imported", 7)]},
        status=200,
    )


async def test_an_export_from_one_tenant_clones_into_another(two_tenants):
    """Tenant cloning (tenancy §H): the envelope's ``tenant`` is ignored and the
    rows land in the importer's tenant — a third one, ``initech`` — with their
    uuids, translation groups and references kept."""
    initech = as_("initech")
    fields = (await two_tenants.get(f"{API}/{POST}/export", headers=as_(ACME))).json()
    made = await two_tenants.post(f"{API}/import", json=fields, headers=initech)
    assert made.status_code == 200, made.text
    document = (await two_tenants.get(f"{RECORDS}/export?format=json", headers=as_(ACME))).json()
    assert document["tenant"] == ACME
    # Two passes, because an import resolves a relation against what is stored
    # before it writes: ``ACME_ONLY`` points at ``SAME``, so ``SAME`` goes first.
    rows = document["records"]
    passes = (
        [r for r in rows if r["uuid"] != ACME_ONLY],
        [r for r in rows if r["uuid"] == ACME_ONLY],
    )
    for part in passes:
        imported = await two_tenants.post(
            f"{RECORDS}/import?dry_run=false",
            content=json.dumps({**document, "records": part}),
            headers={**initech, "Content-Type": "application/json"},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["created"] == len(part), imported.text
    assert len(rows) == 3
    copy = (await two_tenants.get(f"{RECORDS}/{ACME_ONLY}", headers=initech)).json()
    assert (copy["data"]["title"], copy["data"]["link"]["uuid"]) == ("acme only", SAME)
    group = await two_tenants.get(f"{RECORDS}/{SAME}/translations", headers=initech)
    assert sorted(t["locale"] for t in group.json()) == ["de", "en"]
    assert ACME_ONLY in (await two_tenants.get(f"{RECORDS}/{SAME}/referrers", headers=initech)).text
    assert (await two_tenants.get(f"{RECORDS}/{ACME_ONLY}", headers=G)).status_code == 404


@covers("POST /api/records/types/{key}/records/bulk")
@pytest.mark.parametrize("action", ["trash", "publish", "unpublish", "restore", "purge"])
async def test_bulk_refuses_another_tenants_uuid_as_not_found(two_tenants, action):
    foreign = ACME_TRASHED if action in ("restore", "purge") else ACME_ONLY
    response = await same_as_unknown(
        two_tenants,
        "POST",
        f"{RECORDS}/bulk",
        {"uuid": foreign},
        {"uuid": NO_UUID},
        headers=G,
        body=lambda p: {"action": action, "uuids": [GLOBEX_REF, p["uuid"]]},
        status=409,
    )
    failed = response.json()["report"]["failed"]
    assert [f["uuid"] for f in failed if f["uuid"] == foreign] == [foreign]


async def test_bulk_over_the_shared_uuid_acts_on_the_callers_copy(two_tenants):
    done = await two_tenants.post(
        f"{RECORDS}/bulk", json={"action": "unpublish", "uuids": [SAME]}, headers=G
    )
    assert done.status_code == 200, done.text
    assert (await two_tenants.get(f"{RECORDS}/{SAME}", headers=G)).json()["status"] == "draft"


@covers("POST /api/records/types/{key}/records/trash/empty")
async def test_emptying_the_trash_empties_the_callers_only(two_tenants):
    assert (await two_tenants.delete(f"{RECORDS}/{GLOBEX_REF}", headers=G)).status_code == 204
    emptied = await two_tenants.post(f"{RECORDS}/trash/empty", headers=G)
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["purged"] == 1, "acme's trashed record is not globex's to purge"
    trash = await two_tenants.get(f"{RECORDS}?trashed=true", headers=as_(ACME))
    assert _uuids(trash.json()) == {ACME_TRASHED}
