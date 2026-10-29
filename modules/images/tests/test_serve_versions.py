"""Review fixes 4-6 of Task 12: who may share-cache, what a URL promises, HEAD.

4. A tenant something upstream put on the request - even ``default`` - is
   request-specific: never ``public``. Only the host-wide single-tenant
   fallback is (records #196).
5. ``?v=`` names the bytes (generation plus a digest of the key). Since S1
   every answer is ``no-cache`` whatever ``v`` says: a stale or missing one
   gets the current bytes and revalidates like a current one.
6. ``HEAD`` answers every byte route with the same access and cache decisions
   and no body.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from starlette.middleware.base import BaseHTTPMiddleware

from tests.access_support import EDITOR, OWNER, STRANGER, headers
from tests.serve_support import seed_gallery

SHARED = "public, no-cache"
PRIVATE = "private, no-cache"
PUBLIC_NO_CACHE = "public, no-cache"
PRIVATE_NO_CACHE = "private, no-cache"


@pytest_asyncio.fixture
async def g(client, storage):
    return await seed_gallery(client.db_state.session_factory, storage)


class _UpstreamDefault(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):  # type: ignore[override]
        request.state.tenant_id = "default"
        return await call_next(request)


async def test_an_upstream_default_tenant_is_not_shareable(client, g):
    client.app.add_middleware(_UpstreamDefault)
    got = await client.get(g.public_url("pub", "plain", "r/small"))
    assert got.status_code == 200
    assert got.headers["cache-control"] == PRIVATE


async def test_a_context_bound_default_tenant_is_not_shareable(client, g):
    """Bound in the tenant contextvar by an enclosing layer (here: the suite's
    autouse binding), with nothing on ``request.state``: still request-specific."""
    got = await client.get(g.public_url("pub", "plain", "r/small"))
    assert got.status_code == 200
    assert got.headers["cache-control"] == PRIVATE


# --- 5. versions --------------------------------------------------------------


# Shared caching needs the host-wide fallback tenant: nothing bound upstream,
# so this test runs without the suite's default binding (review fix 3.2).
@pytest.mark.unbound_tenant
@pytest.mark.parametrize("tail", ["r/small", "display"])
async def test_public_unversioned_or_stale_is_no_cache(client, g, tail):
    for url in (
        g.public_url("pub", "blurred", tail, versioned=False),
        g.public_url("pub", "blurred", f"{tail}?v=0.deadbeef0000", versioned=False),
    ):
        got = await client.get(url)
        assert got.status_code == 200
        assert got.headers["cache-control"] == PUBLIC_NO_CACHE
        again = await client.get(url, headers={"If-None-Match": got.headers["etag"]})
        assert (again.status_code, again.headers["cache-control"]) == (304, PUBLIC_NO_CACHE)
    current = await client.get(g.public_url("pub", "blurred", tail))
    assert current.headers["cache-control"] == SHARED


@pytest.mark.parametrize("tail", ["r/small", "display"])
async def test_admin_unversioned_or_stale_is_no_cache(client, g, tail):
    for url in (
        g.url("priv", "blurred", tail, versioned=False),
        g.url("priv", "blurred", f"{tail}?v=9.x", versioned=False),
    ):
        got = await client.get(url, headers=headers(OWNER))
        assert got.headers["cache-control"] == PRIVATE_NO_CACHE
    got = await client.get(g.url("priv", "blurred", tail), headers=headers(OWNER))
    assert got.headers["cache-control"] == PRIVATE


async def test_the_version_names_the_key_not_just_the_generation(client, g):
    v = g.version("pub.blurred", "r/small")
    gen, digest = v.split(".")
    assert gen == "1" and len(digest) >= 8
    other = g.version("pub.blurred", "display")
    assert other.split(".")[0] == gen and other != v


async def test_original_ignores_v(client, g):
    got = await client.get(g.url("priv", "plain", "original?v=1.x"), headers=headers(OWNER))
    assert got.headers["cache-control"] == PRIVATE


# --- 6. HEAD ------------------------------------------------------------------


async def test_head_public_rendition_has_headers_and_no_body(client, g):
    url = g.public_url("pub", "blurred", "r/small")
    full = await client.get(url)
    got = await client.head(url)
    assert got.status_code == 200
    assert got.content == b""
    for name in ("etag", "cache-control", "content-length", "content-type"):
        assert got.headers[name] == full.headers[name], name
    again = await client.head(url, headers={"If-None-Match": full.headers["etag"]})
    assert again.status_code == 304


@pytest.mark.parametrize("tail", ["r/small", "display", "original"])
async def test_head_checks_access_like_get(client, g, tail):
    assert (await client.head(g.public_url("priv", "plain", tail))).status_code == 404
    assert (
        await client.head(g.url("priv", "plain", tail), headers=headers(STRANGER))
    ).status_code == 404
    assert (await client.head(g.url("priv", "plain", tail))).status_code == 401
    own = await client.head(g.url("priv", "plain", tail), headers=headers(OWNER))
    assert own.status_code == 200 and own.content == b""


async def test_head_protected_original_is_403_and_no_store_for_the_owner(client, g):
    url = g.url("priv", "blurred", "original")
    assert (await client.head(url, headers=headers(EDITOR))).status_code == 403
    own = await client.head(url, headers=headers(OWNER))
    assert (own.status_code, own.headers["cache-control"]) == (200, "private, no-store")


async def test_head_range_reports_the_partial_length(client, g):
    got = await client.head(
        g.url("priv", "blurred", "display"), headers={**headers(OWNER), "Range": "bytes=0-9"}
    )
    assert got.status_code == 206
    assert got.headers["content-length"] == "10"
    assert got.content == b""
