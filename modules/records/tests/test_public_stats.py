"""``GET {public_route_prefix}/{type_key}/stats`` — the live stats block's number (#88).

One count or one exact sum over what the public listing would show, and not a
row more: published, out of the trash, in the bound tenant, in one language
resolved exactly as the listing resolves it. Everything the listing refuses to
filter or sort by, this refuses to sum or filter by, with the same 400 naming
the field — a sum over a hidden column is the value of that column, one
filter at a time.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sm_records.index import IndexEntry, IndexKind, VirtualField, register_index_provider

from tests.app_harness import ADMIN, api_record, api_type, field, roles
from tests.i18n_helpers import TYPE_KEY, make_record, make_type, publish, translate, use_locales
from tests.isolation_support import ACME, GLOBEX, POST, PUBLIC, covers, reader

_KEY = "parcel"
_STATS = f"{PUBLIC}/{_KEY}/stats"
_FIELDS = [
    field("name"),
    field("area", "number"),
    field("kind"),
    field("notes", indexed=False),
]


def _virtual(record, rtype):
    """A host-computed number the public shape never carries."""
    yield IndexEntry(kind=IndexKind.NUMBER, field_key="risk", value=Decimal(7))


@pytest_asyncio.fixture
async def parcels(public_client):
    register_index_provider(_virtual, fields=[VirtualField("risk", IndexKind.NUMBER)])
    await api_type(
        public_client, _KEY, _FIELDS, display_field="name", slug_field="name", is_public=True
    )
    return public_client


async def _parcel(client, name: str, area=None, *, status: str = "published", kind="a") -> dict:
    data = {"name": name, "kind": kind, **({} if area is None else {"area": area})}
    return await api_record(client, _KEY, data, status=status)


async def _value(client, query: str = "", *, url: str = _STATS, **kwargs):
    resp = await client.get(f"{url}?{query}", **kwargs)
    assert resp.status_code == 200, resp.text
    assert resp.json()["capped"] is False, "nothing here is near max_count"
    return resp.json()["value"]


async def test_count_published_only(parcels):
    for name in ("one", "two", "three"):
        await _parcel(parcels, name)
    await _parcel(parcels, "draft", status="draft")
    binned = await _parcel(parcels, "binned")
    gone = await parcels.delete(
        f"/api/records/types/{_KEY}/records/{binned['uuid']}", headers=roles(ADMIN)
    )
    assert gone.status_code == 204
    assert await _value(parcels, "metric=count") == 3
    assert await _value(parcels) == 3, "count is the default metric"


async def test_private_type_is_404(public_client):
    await api_type(public_client, "secret", _FIELDS, display_field="name", is_public=False)
    await api_record(public_client, "secret", {"name": "x"}, status="published")
    private = await public_client.get(f"{PUBLIC}/secret/stats")
    missing = await public_client.get(f"{PUBLIC}/no-such-type/stats")
    assert private.status_code == missing.status_code == 404
    assert private.json() == missing.json()


async def test_sum_public_number_field(parcels):
    await _parcel(parcels, "a", 1.25)
    await _parcel(parcels, "b", 2.5)
    await _parcel(parcels, "c")
    await _parcel(parcels, "draft", 100, status="draft")
    binned = await _parcel(parcels, "binned", 1000)
    gone = await parcels.delete(
        f"/api/records/types/{_KEY}/records/{binned['uuid']}", headers=roles(ADMIN)
    )
    assert gone.status_code == 204
    assert await _value(parcels, "metric=sum:area") == 3.75
    await _parcel(parcels, "d", 0.25)
    whole = await _value(parcels, "metric=sum:area")
    assert whole == 4 and isinstance(whole, int), "an integral sum is an int"


async def test_sum_over_nothing_is_zero(parcels):
    assert await _value(parcels, "metric=sum:area") == 0


async def test_sum_refuses_hidden_or_non_number(parcels):
    await _parcel(parcels, "a", 1)
    for name in ("risk", "nope", "position", "created_at", "name", "notes", "published_at"):
        resp = await parcels.get(f"{_STATS}?metric=sum:{name}")
        assert resp.status_code == 400, (name, resp.text)
        assert repr(name) in resp.json()["detail"], name


async def test_filter_narrows(parcels):
    await _parcel(parcels, "a", 1, kind="x")
    await _parcel(parcels, "b", 2, kind="x")
    await _parcel(parcels, "c", 4, kind="y")
    assert await _value(parcels, "filter=kind:eq:x") == 2
    assert await _value(parcels, "metric=sum:area&filter=kind:eq:x") == 3
    assert await _value(parcels, "metric=sum:area&filter=area:gte:2") == 6


async def test_hidden_filter_refused(parcels):
    await _parcel(parcels, "a", 1)
    for metric in ("count", "sum:area"):
        for name in ("created_at", "position", "risk", "status", "locale"):
            resp = await parcels.get(f"{_STATS}?metric={metric}&filter={name}:gte:0")
            assert resp.status_code == 400, (metric, name, resp.text)
            assert repr(name) in resp.json()["detail"], (metric, name)


async def test_min_metric_refused(parcels):
    for metric in ("min:area", "max:area", "avg:area", "sum"):
        resp = await parcels.get(f"{_STATS}?metric={metric}")
        assert resp.status_code == 400, (metric, resp.text)


async def test_stats_route_not_shadowed(parcels):
    """``/{type_key}/stats`` is registered before ``/{type_key}/{uuid}``, or
    this would be a 404 for a record whose uuid is "stats"; and a record whose
    *slug* is ``stats`` is still served by its uuid."""
    named = await _parcel(parcels, "stats", 2)
    assert named["slug"] == "stats"
    assert await _value(parcels) == 1
    one = await parcels.get(f"{PUBLIC}/{_KEY}/{named['uuid']}")
    assert one.status_code == 200, one.text
    assert one.json()["slug"] == "stats"


async def test_cache_and_head(parcels):
    await _parcel(parcels, "a", 1)
    got = await parcels.get(_STATS)
    assert got.headers["cache-control"] == "public, max-age=60"
    assert got.headers["etag"].startswith('W/"')
    again = await parcels.get(_STATS, headers={"If-None-Match": got.headers["etag"]})
    assert again.status_code == 304
    head = await parcels.head(_STATS)
    assert head.status_code == 200
    assert head.content == b""


# --- languages -----------------------------------------------------------------------


@pytest_asyncio.fixture
async def site(client):
    use_locales(client, "en", "de")
    await client.app.state.records_module.on_startup(client.app)
    await make_type(client, is_public=True)
    return client


async def test_locale_narrows(site):
    """A translated record counts once — in the language asked for, and in
    the default one when none is — never once per sibling."""
    english = await publish(site, await make_record(site, "About us"))
    await publish(site, (await translate(site, english["uuid"], "de")).json())
    stats = f"{PUBLIC}/{TYPE_KEY}/stats"
    for query in ("", "locale=de", "locale=en"):
        assert await _value(site, query, url=stats) == 1, query
    await publish(site, await make_record(site, "Kontakt", locale="de"))
    assert await _value(site, "locale=de", url=stats) == 2
    assert await _value(site, url=stats) == 1


async def test_locale_resolution_matches_listing(site):
    """Same status, and the stat equals the listing's ``total``, for every
    way a caller can spell the language: none, upper-case, unsupported, and
    one the site has since stopped publishing."""
    english = await publish(site, await make_record(site, "About us"))
    await publish(site, (await translate(site, english["uuid"], "de")).json())
    await publish(site, await make_record(site, "Kontakt", locale="de"))
    listing, stats = f"{PUBLIC}/{TYPE_KEY}", f"{PUBLIC}/{TYPE_KEY}/stats"

    async def same(query: str) -> None:
        listed = await site.get(f"{listing}?{query}")
        counted = await site.get(f"{stats}?{query}")
        assert counted.status_code == listed.status_code, (query, counted.text)
        if listed.status_code == 200:
            assert counted.json()["value"] == listed.json()["total"], query
        else:
            assert counted.json() == listed.json(), query

    for query in ("", "locale=DE", "locale=En", "locale=fr", "locale="):
        await same(query)
    use_locales(site, "en")
    for query in ("", "locale=de", "locale=DE"):
        await same(query)


# --- tenancy -------------------------------------------------------------------------


@covers("GET /api/records/public/{type_key}/stats", "HEAD /api/records/public/{type_key}/stats")
@pytest.mark.unbound_tenant
async def test_other_tenant_not_counted(two_tenants):
    """acme's ``post`` holds ``same`` (score 1) and ``acme only`` (10) plus a
    trashed row; globex's holds ``same`` (1) and ``globex ref`` (3)."""
    url = f"{PUBLIC}/{POST}/stats"
    for tenant, total in ((ACME, 11), (GLOBEX, 4)):
        summed = await _value(two_tenants, "metric=sum:score", url=url, headers=reader(tenant))
        assert summed == total, tenant
        assert await _value(two_tenants, url=url, headers=reader(tenant)) == 2, tenant
        head = await two_tenants.head(url, headers=reader(tenant))
        assert head.status_code == 200
    for method in ("GET", "HEAD"):
        missing = await two_tenants.request(method, url)
        assert missing.status_code == 404, "no tenant resolved is the public 404"
