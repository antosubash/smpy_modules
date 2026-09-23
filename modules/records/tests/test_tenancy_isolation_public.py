"""The isolation matrix, part 4: the anonymous API, caching and cursors — K1, K2, K3.

* **K2.** ``X-Tenant-ID`` selects the tenant an anonymous read runs in; with
  none, a multi-tenant host answers the public 404 and a single-tenant host
  reads ``default``, ignoring the header. Every public answer on a
  multi-tenant host names the header in ``Vary`` (the 304 too), and a
  signed-in caller's answer, whose tenant comes from their account, is
  ``private``. The pagebuilder widget's request shape is scoped the same way.
* **K3.** A keyset cursor carries the tenant it was minted in: replayed in
  another tenant it is the 400 ``CursorError`` on the API and the refused-cursor
  notice on the list screen. An ETag from one tenant never earns a 304 in
  another whose page differs.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sm_records import boot, constants

from tests.app_harness import ADMIN, build_app, roles
from tests.isolation_support import (
    ACME,
    ACME_ONLY,
    API,
    GLOBEX,
    GLOBEX_REF,
    INERTIA,
    NO_KEY,
    NO_UUID,
    POST,
    PUBLIC,
    SAME,
    SECRET,
    VIEW,
    as_,
    covers,
    reader,
    same_as_unknown,
)

pytestmark = pytest.mark.unbound_tenant

TENANT_HEADER = "X-Tenant-ID"


def _vary(response) -> set[str]:
    return {v.strip().lower() for v in response.headers.get("vary", "").split(",") if v.strip()}


@covers("GET /api/records/public/{type_key}", "HEAD /api/records/public/{type_key}")
async def test_the_header_selects_the_tenant_of_an_anonymous_list(two_tenants):
    for tenant, expected in ((ACME, {SAME, ACME_ONLY}), (GLOBEX, {SAME, GLOBEX_REF})):
        listed = await two_tenants.get(f"{PUBLIC}/{POST}", headers=reader(tenant))
        assert {item["uuid"] for item in listed.json()["items"]} == expected
        assert TENANT_HEADER.lower() in _vary(listed)
    for method in ("GET", "HEAD"):
        await same_as_unknown(
            two_tenants,
            method,
            PUBLIC + "/{key}",
            {"key": SECRET},
            {"key": NO_KEY},
            headers=reader(GLOBEX),
        )


@covers("GET /api/records/public/{type_key}/{uuid}", "HEAD /api/records/public/{type_key}/{uuid}")
async def test_the_header_selects_the_tenant_of_an_anonymous_record(two_tenants):
    mine = await two_tenants.get(f"{PUBLIC}/{POST}/{SAME}", headers=reader(GLOBEX))
    assert mine.json()["data"]["title"] == "globex same"
    assert TENANT_HEADER.lower() in _vary(mine)
    for method in ("GET", "HEAD"):
        await same_as_unknown(
            two_tenants,
            method,
            f"{PUBLIC}/{POST}/{{uuid}}",
            {"uuid": ACME_ONLY},
            {"uuid": NO_UUID},
            headers=reader(GLOBEX),
        )


async def test_no_tenant_is_the_public_404_on_a_multi_tenant_host(two_tenants):
    unknown = await two_tenants.get(f"{PUBLIC}/{NO_KEY}", headers=reader(GLOBEX))
    for path in (f"{PUBLIC}/{POST}", f"{PUBLIC}/{POST}/{SAME}"):
        missing = await two_tenants.get(path)
        assert (missing.status_code, missing.json()) == (404, unknown.json())


async def test_every_public_error_names_the_header_and_is_not_stored(two_tenants):
    """Review m1: ``secret`` is a 200 for acme and a 404 for globex at the same
    URL, so a cache that kept globex's 404 under the bare URL would serve it to
    acme. Every error — mapped here or rendered by the host — carries ``Vary``
    and ``no-store``."""
    cases = (
        (404, f"{PUBLIC}/{SECRET}", reader(GLOBEX)),
        (404, f"{PUBLIC}/{SECRET}/{NO_UUID}", reader(ACME)),
        (404, f"{PUBLIC}/{POST}", {}),
        (400, f"{PUBLIC}/{POST}?filter=nosuch:eq:1", reader(GLOBEX)),
        (422, f"{PUBLIC}/{POST}?page=0", reader(GLOBEX)),
    )
    for status, url, headers in cases:
        for method in ("GET", "HEAD"):
            answer = await two_tenants.request(method, url, headers=headers)
            assert answer.status_code == status, (method, url, answer.text)
            assert TENANT_HEADER.lower() in _vary(answer), (method, url)
            assert answer.headers.get("cache-control") == "no-store", (method, url)
    refused = await two_tenants.get(f"{PUBLIC}/{POST}?filter=nosuch:eq:1", headers=reader(GLOBEX))
    assert refused.json() == {"detail": "cannot filter or sort by 'nosuch'"}, "body unchanged"
    served = await two_tenants.get(f"{PUBLIC}/{SECRET}", headers=reader(ACME))
    assert served.status_code == 200
    assert served.headers["cache-control"].startswith("public, "), "a 200 keeps its policy"


async def test_the_widgets_request_is_scoped_by_its_header(two_tenants):
    """What ``utils/public-api.fetchPublicRecords`` sends: no cookie, an
    ``Accept`` header, one filter, one sort, the page size — plus the tenant
    header the widget's Tenant field adds (tenancy §J step 4)."""
    query = "?page_size=5&filter=score:gte:0&sort=-score&locale=en"
    headers = {"Accept": "application/json", **reader(GLOBEX)}
    page = await two_tenants.get(f"{PUBLIC}/{POST}{query}", headers=headers)
    assert page.status_code == 200, page.text
    assert [item["uuid"] for item in page.json()["items"]] == [GLOBEX_REF, SAME]
    assert (await two_tenants.get(f"{PUBLIC}/{POST}{query}")).status_code == 404


async def test_a_signed_in_readers_public_answer_is_private(two_tenants):
    """Their tenant comes from their account, which no request header names,
    so a shared cache keyed on ``Vary`` could hand it to somebody else."""
    anonymous = await two_tenants.get(f"{PUBLIC}/{POST}", headers=reader(GLOBEX))
    signed_in = await two_tenants.get(f"{PUBLIC}/{POST}", headers=as_(GLOBEX))
    assert anonymous.headers["cache-control"].startswith("public, ")
    assert signed_in.headers["cache-control"].startswith("private, ")
    assert signed_in.json() == anonymous.json()


async def test_an_etag_is_revalidated_per_tenant(two_tenants):
    theirs = await two_tenants.get(f"{PUBLIC}/{POST}", headers=reader(ACME))
    tag = theirs.headers["etag"]
    elsewhere = await two_tenants.get(
        f"{PUBLIC}/{POST}", headers={**reader(GLOBEX), "If-None-Match": tag}
    )
    assert elsewhere.status_code == 200, "globex's page is not acme's"
    assert elsewhere.headers["etag"] != tag
    same = await two_tenants.get(f"{PUBLIC}/{POST}", headers={**reader(ACME), "If-None-Match": tag})
    assert same.status_code == 304
    assert TENANT_HEADER.lower() in _vary(same), "the 304 carries Vary too"


async def test_a_single_tenant_host_reads_default_and_ignores_the_header(tmp_path):
    app, db_state = await build_app(tmp_path)
    boot.mount_public_router(app, getattr(app.state, constants.PACKAGE).settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        body = {"key": POST, "label": "Post", "fields": [], "is_public": True}
        assert (await client.post(API, json=body, headers=roles(ADMIN))).status_code == 201
        made = await client.post(
            f"{API}/{POST}/records", json={"data": {}, "status": "published"}, headers=roles(ADMIN)
        )
        assert made.status_code == 201, made.text
        for headers in ({}, reader(ACME)):
            listed = await client.get(f"{PUBLIC}/{POST}", headers=headers)
            assert [i["uuid"] for i in listed.json()["items"]] == [made.json()["uuid"]]
            assert TENANT_HEADER.lower() not in _vary(listed)
            assert listed.headers["cache-control"].startswith("public, ")
            missing = await client.get(f"{PUBLIC}/nosuch", headers=headers)
            assert missing.status_code == 404
            assert TENANT_HEADER.lower() not in _vary(missing), "single mode: errors as before"
            assert "cache-control" not in missing.headers
    await db_state.engine.dispose()


# --- K3: cursors ---------------------------------------------------------------------


async def _cursor(client, url: str, headers: dict[str, str]) -> str:
    page = await client.get(url, headers=headers)
    assert page.status_code == 200, page.text
    cursor = page.json()["next_cursor"]
    assert cursor, page.text
    return cursor


async def test_an_admin_cursor_minted_in_one_tenant_is_refused_in_another(two_tenants):
    url = f"{API}/{POST}/records?sort=score&page_size=1"
    cursor = await _cursor(two_tenants, url, as_(ACME))
    assert (await two_tenants.get(f"{url}&after={cursor}", headers=as_(ACME))).status_code == 200
    replayed = await two_tenants.get(f"{url}&after={cursor}", headers=as_(GLOBEX))
    assert replayed.status_code == 400, replayed.text
    assert "cursor" in replayed.json()["detail"]
    screen = await two_tenants.get(
        f"{VIEW}/{POST}?sort=score&page_size=1&after={cursor}", headers={**as_(GLOBEX), **INERTIA}
    )
    assert screen.status_code == 200, "a page navigation never errors"
    props = screen.json()["props"]
    assert props["errors"] == {"filter": "bad_cursor"}
    assert props["records"]["items"] == []


async def test_a_public_cursor_minted_in_one_tenant_is_refused_in_another(two_tenants):
    url = f"{PUBLIC}/{POST}?sort=score&page_size=1"
    cursor = await _cursor(two_tenants, url, reader(ACME))
    assert (await two_tenants.get(f"{url}&after={cursor}", headers=reader(ACME))).status_code == 200
    replayed = await two_tenants.get(f"{url}&after={cursor}", headers=reader(GLOBEX))
    assert replayed.status_code == 400, replayed.text
