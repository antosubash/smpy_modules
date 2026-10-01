"""The isolation matrix, part 1: types, type keys and the route table — K1.

A caller in ``globex`` naming ``acme``'s type key gets exactly what naming a
key nobody has gets, on every route that takes a key: the API's, the
screens', and the schema preview's. Naming the key both tenants have (``post``)
reaches ``globex``'s own type and nothing of ``acme``'s.

``two_tenants`` (``tests/isolation_support.py``) checks on the way out that
no ``acme`` row changed, so every case here is also a write-isolation case.

:func:`test_every_route_has_an_isolation_case` is parametrised over the routes
the module really mounts. A new route fails it until somebody writes its
case — in this file, ``…_io`` or ``…_public`` — and marks it with ``@covers``.
"""

from __future__ import annotations

import pytest
from sm_records import constants

# Imported for their ``@covers`` marks: the route table is checked against all four.
from tests import (  # noqa: F401
    test_tenancy_isolation_io,
    test_tenancy_isolation_public,
    test_tenancy_isolation_records,
)
from tests.isolation_support import (
    ACME,
    API,
    COVERED,
    GLOBEX,
    INERTIA,
    NO_KEY,
    POST,
    SECRET,
    VIEW,
    as_,
    covers,
    route_table,
    same_as_unknown,
)

pytestmark = pytest.mark.unbound_tenant

G = as_(GLOBEX)
KEYS = ({"key": SECRET}, {"key": NO_KEY})


@pytest.mark.parametrize("route", route_table(), ids=lambda r: f"{r[0]} {r[1]}")
def test_every_route_has_an_isolation_case(route):
    assert route in COVERED, f"{route} has no tenancy isolation case; add one with @covers"


# Every route that resolves a type key, with a body it would accept, so the
# answer is the type lookup's and not a validation error that came first.
_BY_KEY = [
    ("GET", "/{key}", None),
    ("PUT", "/{key}", {"expected_version": 1, "label": "x"}),
    ("DELETE", "/{key}?confirm_record_count=1", None),
    ("POST", "/{key}/reindex", None),
    ("GET", "/{key}/export", None),
    ("GET", "/{key}/revisions", None),
    ("POST", "/{key}/revisions/1/restore", {"expected_version": 1}),
    ("POST", "/{key}/schema/preview", {"fields": []}),
    ("GET", "/{key}/schema/preview/00000000000000000000000000000000", None),
    ("GET", "/{key}/records", None),
    ("POST", "/{key}/records", {"data": {"title": "x"}}),
    ("GET", "/{key}/records/aggregate", None),
    ("GET", "/{key}/records/export", None),
    ("POST", "/{key}/records/import", {"records": []}),
    ("POST", "/{key}/records/bulk", {"action": "trash", "uuids": ["c" * 32]}),
    ("POST", "/{key}/records/trash/empty", None),
    ("GET", "/{key}/records/{uuid}", None),
    ("PUT", "/{key}/records/{uuid}", {"expected_version": 1, "data": {}}),
    ("DELETE", "/{key}/records/{uuid}", None),
    ("POST", "/{key}/records/{uuid}/restore", None),
    ("DELETE", "/{key}/records/{uuid}/purge", None),
    ("GET", "/{key}/records/{uuid}/translations", None),
    ("POST", "/{key}/records/{uuid}/translations", {"locale": "de"}),
    ("GET", "/{key}/records/{uuid}/referrers", None),
    ("GET", "/{key}/records/{uuid}/revisions", None),
    ("GET", "/{key}/records/{uuid}/revisions/1", None),
    ("POST", "/{key}/records/{uuid}/revisions/1/restore", {"expected_version": 1}),
]


@covers(
    "PUT /api/records/types/{key}",
    "DELETE /api/records/types/{key}",
    "POST /api/records/types/{key}/reindex",
    "GET /api/records/types/{key}/export",
    "POST /api/records/types/{key}/schema/preview",
    "GET /api/records/types/{key}/schema/preview/{job}",
)
@pytest.mark.parametrize(("method", "suffix", "body"), _BY_KEY, ids=lambda v: str(v))
async def test_another_tenants_type_key_is_an_unknown_key(two_tenants, method, suffix, body):
    foreign, unknown = ({**k, "uuid": "c" * 32} for k in KEYS)
    await same_as_unknown(
        two_tenants,
        method,
        API + suffix,
        foreign,
        unknown,
        headers=G,
        body=(lambda _p: body) if body is not None else None,
    )


_SCREENS = ["/types/{key}", "/{key}", "/{key}/new", "/{key}/" + "c" * 32]


@covers(
    "GET /admin/records/types/{key}",
    "GET /admin/records/{key}",
    "GET /admin/records/{key}/new",
)
@pytest.mark.parametrize("suffix", _SCREENS)
async def test_another_tenants_type_key_is_an_unknown_screen(two_tenants, suffix):
    for headers in ({**G, **INERTIA}, G):  # the Inertia visit and the first load
        await same_as_unknown(two_tenants, "GET", VIEW + suffix, *KEYS, headers=headers)


@covers("GET /api/records/types", "GET /admin/records/")
async def test_the_type_lists_are_the_callers_tenant(two_tenants):
    listed = await two_tenants.get(API, headers=G)
    assert [(t["key"], t["label"]) for t in listed.json()["items"]] == [(POST, "globex post")]
    hub = await two_tenants.get(f"{VIEW}/", headers={**G, **INERTIA})
    assert [t["key"] for t in hub.json()["props"]["types"]] == [POST]


@covers("GET /admin/records/types/new")
async def test_the_new_type_screen_offers_only_the_callers_types_as_targets(two_tenants):
    screen = await two_tenants.get(f"{VIEW}/types/new", headers={**G, **INERTIA})
    assert screen.status_code == 200, screen.text
    assert [t["key"] for t in screen.json()["props"]["target_types"]] == [POST]


@covers("POST /api/records/types")
async def test_a_key_another_tenant_uses_is_free_here(two_tenants):
    """No "already exists" oracle: ``secret`` is taken in ``acme`` only."""
    body = {"key": SECRET, "label": "mine", "fields": []}
    assert (await two_tenants.post(API, json=body, headers=G)).status_code == 201
    assert (await two_tenants.get(f"{API}/{SECRET}", headers=G)).json()["label"] == "mine"


@covers("POST /api/records/types/import")
async def test_another_tenants_type_export_imports_here_as_a_new_type(two_tenants):
    exported = await two_tenants.get(f"{API}/{SECRET}/export", headers=as_(ACME))
    imported = await two_tenants.post(f"{API}/import", json=exported.json(), headers=G)
    assert imported.status_code == 200, imported.text
    assert imported.json()["record_count"] == 0, "the definition travels, never the rows"


@covers("GET /api/records/types/{key}")
async def test_the_shared_key_reads_edits_and_deletes_the_callers_type(two_tenants):
    mine = (await two_tenants.get(f"{API}/{POST}", headers=G)).json()
    assert mine["label"] == "globex post"
    assert mine["record_count"] == 2, "acme's records are not counted"
    edited = await two_tenants.put(
        f"{API}/{POST}", json={"expected_version": mine["version"], "label": "renamed"}, headers=G
    )
    assert edited.status_code == 200, edited.text
    reindexed = await two_tenants.post(f"{API}/{POST}/reindex", headers=G)
    assert reindexed.status_code == 202, reindexed.text
    exported = (await two_tenants.get(f"{API}/{POST}/export", headers=G)).json()
    assert exported["label"] == "renamed"
    gone = await two_tenants.delete(f"{API}/{POST}?confirm_record_count=2", headers=G)
    assert gone.status_code == 204, gone.text
    assert (await two_tenants.get(f"{API}/{POST}", headers=as_(ACME))).status_code == 200


@covers(
    "GET /api/records/types/{key}/revisions",
    "POST /api/records/types/{key}/revisions/{version}/restore",
)
async def test_type_revisions_are_the_callers(two_tenants):
    mine = (await two_tenants.get(f"{API}/{POST}", headers=G)).json()
    await two_tenants.put(
        f"{API}/{POST}", json={"expected_version": mine["version"], "label": "v2"}, headers=G
    )
    listed = (await two_tenants.get(f"{API}/{POST}/revisions", headers=G)).json()
    theirs = (await two_tenants.get(f"{API}/{POST}/revisions", headers=as_(ACME))).json()
    assert {r["id"] for r in listed["items"]}.isdisjoint({r["id"] for r in theirs["items"]})
    back = await two_tenants.post(
        f"{API}/{POST}/revisions/1/restore",
        json={"expected_version": mine["version"] + 1},
        headers=G,
    )
    assert back.status_code == 200, back.text


@covers("GET /api/records/types/{key}/schema/preview/{job}")
async def test_a_preview_scans_the_callers_records_and_its_job_is_not_theirs(two_tenants):
    fields = (await two_tenants.get(f"{API}/{POST}", headers=G)).json()["fields"]
    report = await two_tenants.post(
        f"{API}/{POST}/schema/preview", json={"fields": fields, "rescan": True}, headers=G
    )
    assert report.status_code == 200, report.text
    assert report.json()["report"]["checked"] == 2, "acme's post records are not scanned"

    # A deferred draft preview in acme; its job id under globex's ``post``.
    getattr(two_tenants.app.state, constants.PACKAGE).settings.preview_sync_limit = 0
    stricter = [{**f, "required": True} if f["key"] == "title" else f for f in fields]
    started = await two_tenants.post(
        f"{API}/{POST}/schema/preview", json={"fields": stricter}, headers=as_(ACME)
    )
    assert started.status_code == 202, started.text
    job = started.json()["job"]
    theirs = await two_tenants.get(f"{API}/{POST}/schema/preview/{job}", headers=as_(ACME))
    assert theirs.status_code == 200, theirs.text
    template = f"{API}/{POST}/schema/preview/{{job}}"
    await same_as_unknown(two_tenants, "GET", template, {"job": job}, {"job": "0" * 32}, headers=G)
