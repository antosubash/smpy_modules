"""The isolation matrix, part 2: one record by uuid — K1.

Under the type key both tenants have, ``globex`` naming a uuid only ``acme``
holds gets what naming a uuid nobody holds gets, on every route that takes
one. Naming :data:`SAME`, the uuid both hold, reaches ``globex``'s copy and
never ``acme``'s: its revisions, its translation group (whose id is the same
string in both tenants), its referrers, its trash.

``two_tenants`` checks on the way out that no ``acme`` row changed.
"""

from __future__ import annotations

import pytest
from sm_records.models import Record
from sqlalchemy import update

from tests.isolation_support import (
    ACME,
    ACME_ONLY,
    ACME_TRASHED,
    API,
    GLOBEX,
    GLOBEX_REF,
    INERTIA,
    NO_REVISION,
    NO_UUID,
    POST,
    SAME,
    VIEW,
    as_,
    covers,
    link,
    same_as_unknown,
)

pytestmark = pytest.mark.unbound_tenant

G = as_(GLOBEX)
RECORDS = f"{API}/{POST}/records"
UUIDS = ({"uuid": ACME_ONLY}, {"uuid": NO_UUID})


async def _version(client, uuid: str, headers=G) -> int:
    return (await client.get(f"{RECORDS}/{uuid}", headers=headers)).json()["version"]


_BY_UUID = [
    ("GET", "/{uuid}", None),
    ("PUT", "/{uuid}", {"expected_version": 1, "data": {"title": "x"}}),
    ("DELETE", "/{uuid}", None),
    ("GET", "/{uuid}/translations", None),
    ("POST", "/{uuid}/translations", {"locale": "de"}),
    ("GET", "/{uuid}/referrers", None),
    ("GET", "/{uuid}/revisions", None),
    ("GET", "/{uuid}/revisions/1", None),
    ("POST", "/{uuid}/revisions/1/restore", {"expected_version": 1}),
]


@covers(
    "PUT /api/records/types/{key}/records/{uuid}",
    "DELETE /api/records/types/{key}/records/{uuid}",
    "GET /api/records/types/{key}/records/{uuid}/revisions",
)
@pytest.mark.parametrize(("method", "suffix", "body"), _BY_UUID, ids=lambda v: str(v))
async def test_another_tenants_uuid_is_an_unknown_uuid(two_tenants, method, suffix, body):
    await same_as_unknown(
        two_tenants,
        method,
        RECORDS + suffix,
        *UUIDS,
        headers=G,
        body=(lambda _p: body) if body is not None else None,
    )


@covers(
    "POST /api/records/types/{key}/records/{uuid}/restore",
    "DELETE /api/records/types/{key}/records/{uuid}/purge",
)
@pytest.mark.parametrize(("method", "suffix"), [("POST", "/restore"), ("DELETE", "/purge")])
async def test_another_tenants_trash_is_unknown(two_tenants, method, suffix):
    template = RECORDS + "/{uuid}" + suffix
    await same_as_unknown(
        two_tenants, method, template, {"uuid": ACME_TRASHED}, {"uuid": NO_UUID}, headers=G
    )


@covers("GET /api/records/types/{key}/records/{uuid}", "GET /admin/records/{key}/{uuid}")
async def test_the_shared_uuid_reads_the_callers_copy(two_tenants):
    mine = await two_tenants.get(f"{RECORDS}/{SAME}", headers=G)
    assert mine.json()["data"]["title"] == "globex same"
    assert mine.json()["translation_group"] == SAME
    screen = await two_tenants.get(f"{VIEW}/{POST}/{SAME}", headers={**G, **INERTIA})
    assert screen.json()["props"]["record"]["data"]["title"] == "globex same"
    for headers in ({**G, **INERTIA}, G):
        await same_as_unknown(
            two_tenants, "GET", f"{VIEW}/{POST}/{{uuid}}", *UUIDS, headers=headers
        )


async def test_the_shared_uuid_edits_trashes_restores_and_purges_the_callers_copy(two_tenants):
    """``acme``'s ``SAME`` is referenced by ``ACME_ONLY`` under ``restrict``;
    ``globex``'s by ``GLOBEX_REF``. Once ``globex`` drops its own reference, its
    ``SAME`` is free to go — ``acme``'s reference does not hold it."""
    edited = await two_tenants.put(
        f"{RECORDS}/{SAME}",
        json={"expected_version": await _version(two_tenants, SAME), "data": {"title": "g2"}},
        headers=G,
    )
    assert edited.status_code == 200, edited.text
    blocked = await two_tenants.delete(f"{RECORDS}/{SAME}", headers=G)
    assert blocked.status_code == 409, "globex's own reference still holds it"
    assert (blocked.json()["total"], blocked.json()["referrers"]) == (1, [GLOBEX_REF])
    assert (await two_tenants.delete(f"{RECORDS}/{GLOBEX_REF}", headers=G)).status_code == 204
    assert (await two_tenants.delete(f"{RECORDS}/{SAME}", headers=G)).status_code == 204
    assert (await two_tenants.post(f"{RECORDS}/{SAME}/restore", headers=G)).status_code == 200
    assert (await two_tenants.delete(f"{RECORDS}/{SAME}", headers=G)).status_code == 204
    assert (await two_tenants.delete(f"{RECORDS}/{SAME}/purge", headers=G)).status_code == 204
    assert (await two_tenants.get(f"{RECORDS}/{SAME}", headers=as_(ACME))).status_code == 200


@covers(
    "GET /api/records/types/{key}/records/{uuid}/translations",
    "POST /api/records/types/{key}/records/{uuid}/translations",
)
async def test_the_shared_translation_group_is_the_callers(two_tenants):
    """The group id is ``SAME`` in both tenants, and ``acme``'s group already
    has a German sibling; ``globex``'s has none, so its German one is free."""
    listed = await two_tenants.get(f"{RECORDS}/{SAME}/translations", headers=G)
    assert [(t["locale"], t["uuid"]) for t in listed.json()] == [("en", SAME)]
    german = await two_tenants.post(
        f"{RECORDS}/{SAME}/translations", json={"locale": "de"}, headers=G
    )
    assert german.status_code == 201, german.text
    assert german.json()["translation_group"] == SAME
    listed = await two_tenants.get(f"{RECORDS}/{SAME}?translations=true", headers=G)
    assert sorted(t["locale"] for t in listed.json()["translations"]) == ["de", "en"]


@covers("GET /api/records/types/{key}/records/{uuid}/referrers")
async def test_referrers_of_the_shared_uuid_are_the_callers(two_tenants):
    theirs = await two_tenants.get(f"{RECORDS}/{SAME}/referrers", headers=as_(ACME))
    mine = await two_tenants.get(f"{RECORDS}/{SAME}/referrers", headers=G)
    assert ACME_ONLY in theirs.text and GLOBEX_REF not in theirs.text
    assert GLOBEX_REF in mine.text and ACME_ONLY not in mine.text


@covers(
    "GET /api/records/types/{key}/records/{uuid}/revisions/{revision_id}",
    "POST /api/records/types/{key}/records/{uuid}/revisions/{revision_id}/restore",
)
async def test_another_tenants_revision_id_is_an_unknown_revision(two_tenants):
    theirs = await two_tenants.get(f"{RECORDS}/{SAME}/revisions", headers=as_(ACME))
    mine = await two_tenants.get(f"{RECORDS}/{SAME}/revisions", headers=G)
    foreign = theirs.json()["items"][0]["id"]
    assert foreign not in {r["id"] for r in mine.json()["items"]}
    assert {r["display_title"] for r in mine.json()["items"]} == {"globex same"}
    probes = ({"rev": foreign}, {"rev": NO_REVISION})
    await same_as_unknown(
        two_tenants, "GET", f"{RECORDS}/{SAME}/revisions/{{rev}}", *probes, headers=G
    )
    version = await _version(two_tenants, SAME)
    await same_as_unknown(
        two_tenants,
        "POST",
        f"{RECORDS}/{SAME}/revisions/{{rev}}/restore",
        *probes,
        headers=G,
        body=lambda _p: {"expected_version": version},
    )
    own = mine.json()["items"][0]["id"]
    back = await two_tenants.post(
        f"{RECORDS}/{SAME}/revisions/{own}/restore", json={"expected_version": version}, headers=G
    )
    assert back.status_code == 200, back.text


@covers("POST /api/records/types/{key}/records")
async def test_a_relation_to_another_tenants_record_is_a_missing_one(two_tenants):
    await same_as_unknown(
        two_tenants,
        "POST",
        RECORDS,
        *UUIDS,
        headers=G,
        body=lambda p: {"data": {"title": "new", "link": link(p["uuid"])}},
        status=422,
    )
    version = await _version(two_tenants, GLOBEX_REF)
    await same_as_unknown(
        two_tenants,
        "PUT",
        f"{RECORDS}/{GLOBEX_REF}",
        *UUIDS,
        headers=G,
        body=lambda p: {
            "expected_version": version,
            "data": {"title": "x", "link": link(p["uuid"])},
        },
        status=422,
    )


async def test_expand_never_reaches_into_another_tenant(two_tenants):
    """A reference stored behind the validator's back (a hand edit, an old
    import) to ``acme``'s record expands exactly like a dangling one."""
    table = Record.__table__

    async def point_at(uuid: str) -> dict:
        async with two_tenants.db_state.session_factory() as session:  # type: ignore[attr-defined]
            await session.execute(
                update(table)
                .where(table.c.tenant_id == GLOBEX, table.c.uuid == GLOBEX_REF)
                .values(data={"title": "globex ref", "score": 3, "link": link(uuid)})
            )
            await session.commit()
        resp = await two_tenants.get(f"{RECORDS}/{GLOBEX_REF}?expand=link", headers=G)
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]["link"]

    foreign, dangling = await point_at(ACME_ONLY), await point_at(NO_UUID)
    assert foreign == {**dangling, "uuid": ACME_ONLY}
    assert "acme" not in str(foreign)
