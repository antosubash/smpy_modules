"""The anonymous twins under ``/api/images/public/c/{slug}/images/{id}/…`` (Task 12).

Only a public collection is served there, to anyone: the twin answers as the
anonymous surface even to a signed-in owner. And only there, for a rendition
or display copy, on a host where nothing request-specific picked the tenant,
is a response shareable (CLAUDE.md, records #196, pagebuilder/news #192).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from file_storage.backends.filesystem import FilesystemBackend
from sm_images.models import Visibility
from sm_images.tenancy import tenant_scope
from starlette.middleware.base import BaseHTTPMiddleware

from tests.support.access import OWNER, STRANGER, collection, headers, image
from tests.support.isolation import ACME
from tests.support.serve import seed_gallery

SHARED = "public, no-cache"
PRIVATE = "private, no-cache"


@pytest_asyncio.fixture
async def g(client, storage):
    return await seed_gallery(client.db_state.session_factory, storage)


# Shared caching needs the host-wide fallback tenant: nothing bound upstream,
# so this test runs without the suite's default binding (review fix 3.2).
@pytest.mark.unbound_tenant
@pytest.mark.parametrize(("tail", "what"), [("r/small", "small"), ("display", "display")])
async def test_public_rendition_and_display_are_shareable(client, g, tail, what):
    got = await client.get(g.public_url("pub", "blurred", tail))
    assert got.status_code == 200, got.text
    assert got.content == g.bytes[f"pub.blurred.{what}"]
    assert got.headers["cache-control"] == SHARED
    again = await client.get(
        g.public_url("pub", "blurred", tail), headers={"If-None-Match": got.headers["etag"]}
    )
    assert (again.status_code, again.headers["cache-control"]) == (304, SHARED)
    assert again.headers["etag"] == got.headers["etag"]


# Shared caching needs the host-wide fallback tenant: nothing bound upstream,
# so this test runs without the suite's default binding (review fix 3.2).
@pytest.mark.unbound_tenant
async def test_public_display_supports_ranges(client, g):
    got = await client.get(
        g.public_url("pub", "blurred", "display"), headers={"Range": "bytes=0-9"}
    )
    assert got.status_code == 206
    assert got.content == g.bytes["pub.blurred.display"][:10]
    assert got.headers["cache-control"] == SHARED


async def test_public_unprotected_original_is_served_but_never_shareable(client, g):
    got = await client.get(g.public_url("pub", "plain", "original"))
    assert got.status_code == 200
    assert got.content == g.bytes["pub.plain.original"]
    assert got.headers["cache-control"] == PRIVATE


@pytest.mark.parametrize("who", [None, OWNER])
async def test_public_protected_original_is_403_even_to_the_owner(client, g, who):
    got = await client.get(g.public_url("pub", "blurred", "original"), headers=headers(who))
    assert got.status_code == 403
    assert g.bytes["pub.blurred.original"] not in got.content


@pytest.mark.parametrize("who", [None, STRANGER, OWNER])
@pytest.mark.parametrize("tail", ["r/small", "display", "original"])
async def test_a_private_collection_is_404_on_the_public_twin(client, g, who, tail):
    got = await client.get(g.public_url("priv", "plain", tail), headers=headers(who))
    assert got.status_code == 404
    assert g.bytes["priv.plain.original"] not in got.content


async def test_an_internal_collection_is_404_on_the_public_twin(client, storage):
    from sm_images.storage import ImageStore

    internal = collection("inside", Visibility.INTERNAL)
    async with client.db_state.session_factory() as s:
        s.add(internal)
        await s.flush()
        pic = image(internal, "in.jpg")
        s.add(pic)
        await s.commit()
    await ImageStore(storage).put(pic.storage_key, b"x" * 10, content_type="image/jpeg", size=10)
    got = await client.get(f"/api/images/public/c/inside/images/{pic.id}/display")
    assert got.status_code == 404


async def test_an_image_named_under_another_collections_slug_is_404(client, g):
    # The public slug, the private collection's image.
    url = g.public_url("priv", "plain", "display", slug=g.slugs["pub"])
    assert (await client.get(url)).status_code == 404


async def test_public_unknown_size_is_404(client, g):
    assert (await client.get(g.public_url("pub", "plain", "r/huge"))).status_code == 404


async def test_public_errors_are_never_stored(client, g):
    for url in (
        g.public_url("priv", "plain", "display"),
        g.public_url("pub", "plain", "r/huge"),
        g.public_url("pub", "blurred", "original"),
    ):
        got = await client.get(url)
        assert got.status_code in (403, 404)
        assert got.headers["cache-control"] == "no-store"


class _Upstream(BaseHTTPMiddleware):
    """A layer above images that resolved the tenant for this request."""

    async def dispatch(self, request, call_next):  # type: ignore[override]
        request.state.tenant_id = ACME
        return await call_next(request)


@pytest.mark.unbound_tenant
async def test_a_tenant_resolved_upstream_is_never_shareable(client, storage):
    """A single-tenant detection serving a tenant someone upstream picked (#196)."""
    client.app.add_middleware(_Upstream)
    with tenant_scope(ACME):
        g = await seed_gallery(client.db_state.session_factory, storage)
    got = await client.get(g.public_url("pub", "plain", "r/small"))
    assert got.status_code == 200, got.text
    assert got.headers["cache-control"] == PRIVATE
    again = await client.get(
        g.public_url("pub", "plain", "r/small"), headers={"If-None-Match": got.headers["etag"]}
    )
    assert (again.status_code, again.headers["cache-control"]) == (304, PRIVATE)


@pytest.mark.unbound_tenant
async def test_multi_tenant_public_answer_is_private(two_tenants, tmp_path):
    client = two_tenants
    backend = FilesystemBackend(tmp_path / "mt-storage")
    client.app.state.file_storage = SimpleNamespace(backend=backend)
    with tenant_scope(ACME):
        g = await seed_gallery(client.db_state.session_factory, backend)
    for tail in ("r/small", "display"):
        got = await client.get(g.public_url("pub", "plain", tail), headers={"X-Tenant-ID": ACME})
        assert got.status_code == 200, got.text
        assert got.headers["cache-control"] == PRIVATE
    # Another tenant's visitor: the same URL is somebody else's nothing.
    other = await client.get(
        g.public_url("pub", "plain", "display"), headers={"X-Tenant-ID": "globex"}
    )
    assert other.status_code == 404
    # No tenant at all: the anonymous surface's 404.
    assert (await client.get(g.public_url("pub", "plain", "display"))).status_code == 404
