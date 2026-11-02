"""``/api/images/public/stats``: the counts behind the ``ImageStats`` block (#88).

Each count is what the anonymous gallery would list - not trashed, passing the
redaction gate, with a current ``small`` rendition - over one public collection
or every one of them, never ``Collection.image_count``. A private, internal,
trashed or unknown slug is the public 404, and every refusal is ``no-store``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.models import Visibility
from starlette.middleware.base import BaseHTTPMiddleware

from tests.support.isolation import ACME
from tests.support.public_stats import (
    URL,
    blur_installed,  # noqa: F401 - autouse
    stat,
)
from tests.support.public_stats import seed as _seed

SHARED = "public, max-age=60"
PRIVATE = "private, no-cache"


async def _value(client, metric, slug=None, **kw):
    answer = await stat(client, metric, slug, **kw)
    assert answer["capped"] is False
    return answer["value"]


async def test_counts_public_ready_images(client):
    (coll,) = await _seed(client.db_state.session_factory, [(Visibility.PUBLIC, False, 3, 2, 1)])
    assert await _value(client, "images", coll.slug) == 3
    assert await _value(client, "images") == 3
    assert await _value(client, "located", coll.slug) == 2
    assert await _value(client, "located") == 2


async def test_all_collections_total_excludes_private(client):
    specs = [
        (Visibility.PUBLIC, False, 2, 1, 0),
        (Visibility.PUBLIC, False, 3, 3, 0),
        (Visibility.PRIVATE, False, 5, 5, 0),
        (Visibility.INTERNAL, False, 7, 7, 0),
        (Visibility.PUBLIC, True, 11, 11, 0),
    ]
    await _seed(client.db_state.session_factory, specs)
    assert await _value(client, "images") == 5
    assert await _value(client, "located") == 4
    assert await _value(client, "collections") == 2


async def test_each_collection_keeps_its_own_gate(client):
    """One total over collections with different redaction gates: the blurred
    one holds back its unsettled image, the plain one (no mutator) shows its
    images without any step run - neither gate leaks onto the other."""
    specs = [(Visibility.PUBLIC, False, 3, 2, 1), (Visibility.PUBLIC, False, 2, 1, 0)]
    await _seed(client.db_state.session_factory, specs)
    assert await _value(client, "images") == 5
    assert await _value(client, "located") == 3


@pytest.mark.parametrize(("visibility", "trashed"), [
    (Visibility.PRIVATE, False), (Visibility.INTERNAL, False), (Visibility.PUBLIC, True),
])  # fmt: skip
async def test_private_slug_is_404_no_store(client, visibility, trashed):
    (coll,) = await _seed(client.db_state.session_factory, [(visibility, trashed, 1, 1, 0)])
    for slug in (coll.slug, "no-such-collection"):
        got = await client.get(URL, params={"metric": "images", "collection": slug})
        assert got.status_code == 404
        assert got.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("query", [{"metric": "bytes"}, {}, {"metric": "image_count"}])
async def test_unknown_metric_is_400_no_store(client, query):
    got = await client.get(URL, params=query)
    assert got.status_code == 400
    assert got.headers["cache-control"] == "no-store"


async def test_head_answers(client):
    (coll,) = await _seed(client.db_state.session_factory, [(Visibility.PUBLIC, False, 1, 0, 0)])
    got = await client.head(URL, params={"metric": "images", "collection": coll.slug})
    assert got.status_code == 200
    assert got.content == b""
    assert got.headers["cache-control"] == PRIVATE
    bad = await client.head(URL, params={"metric": "nope"})
    assert (bad.status_code, bad.headers["cache-control"]) == (400, "no-store")


@pytest.mark.unbound_tenant
async def test_other_tenant_not_counted(client):
    factory = client.db_state.session_factory
    (theirs,) = await _seed(factory, [(Visibility.PUBLIC, False, 4, 4, 0)], tenant=ACME)
    await _seed(factory, [(Visibility.PUBLIC, False, 1, 0, 0)])
    assert await _value(client, "images") == 1
    assert await _value(client, "collections") == 1
    got = await client.get(URL, params={"metric": "images", "collection": theirs.slug})
    assert got.status_code == 404


# ---- who may share the answer ------------------------------------------------


def _upstream(tenant):
    class _Upstream(BaseHTTPMiddleware):
        """A layer above images that resolved the tenant for this request."""

        async def dispatch(self, request, call_next):  # type: ignore[override]
            request.state.tenant_id = tenant
            return await call_next(request)

    return _Upstream


async def _cache_controls(client, slug, **kw):
    single = await client.get(URL, params={"metric": "images", "collection": slug}, **kw)
    total = await client.get(URL, params={"metric": "located"}, **kw)
    assert (single.status_code, total.status_code) == (200, 200), (single.text, total.text)
    assert "etag" not in single.headers and "etag" not in total.headers
    return single.headers["cache-control"], total.headers["cache-control"]


@pytest.mark.unbound_tenant
async def test_cache_headers_shared_only_for_the_host_wide_fallback(client):
    (coll,) = await _seed(client.db_state.session_factory, [(Visibility.PUBLIC, False, 1, 1, 0)])
    assert await _cache_controls(client, coll.slug) == (SHARED, SHARED)


@pytest.mark.unbound_tenant
@pytest.mark.parametrize("tenant", [ACME, DEFAULT_TENANT])
async def test_cache_headers_private_for_an_upstream_tenant(client, tenant):
    """Upstream chose it - even ``default`` - so it is request-specific (#196)."""
    client.app.add_middleware(_upstream(tenant))
    (coll,) = await _seed(
        client.db_state.session_factory, [(Visibility.PUBLIC, False, 1, 1, 0)], tenant=tenant
    )
    assert await _cache_controls(client, coll.slug) == (PRIVATE, PRIVATE)


async def test_cache_headers_private_for_a_bound_tenant_context(client):
    (coll,) = await _seed(client.db_state.session_factory, [(Visibility.PUBLIC, False, 1, 1, 0)])
    assert await _cache_controls(client, coll.slug) == (PRIVATE, PRIVATE)


@pytest_asyncio.fixture
async def acme_public(two_tenants):
    specs = [(Visibility.PUBLIC, False, 2, 1, 0)]
    (coll,) = await _seed(two_tenants.db_state.session_factory, specs, tenant=ACME)
    return coll


@pytest.mark.unbound_tenant
async def test_multi_tenant_answers_are_private(two_tenants, acme_public):
    client = two_tenants
    tenant = {"X-Tenant-ID": ACME}
    assert await _cache_controls(client, acme_public.slug, headers=tenant) == (PRIVATE, PRIVATE)
    assert await _value(client, "images", headers=tenant) == 2
    other = await client.get(URL, params={"metric": "images"}, headers={"X-Tenant-ID": "globex"})
    assert other.json() == {"value": 0, "capped": False}
    for params in ({"metric": "images"}, {"metric": "images", "collection": acme_public.slug}):
        got = await client.get(URL, params=params)
        assert (got.status_code, got.headers["cache-control"]) == (404, "no-store")
