"""Every image byte response revalidates, so a revocation reaches caches (S1).

A versioned public rendition used to be ``public, max-age=31536000, immutable``:
a shared cache kept serving the URL after the collection went private,
``protect_originals`` was switched on, or anonymization was enabled. Now every
response a later change can revoke is ``no-cache`` with a strong ETag, so each
use is a conditional request, and the 304 is answered only after the full
access and redaction check.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_images.models import Collection, Visibility
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope
from sqlalchemy import update

from tests.access_support import OWNER, STRANGER, headers
from tests.serve_support import seed_gallery

PUBLIC = "public, no-cache"
PRIVATE = "private, no-cache"
NO_STORE = "private, no-store"


@pytest_asyncio.fixture
async def g(client, storage):
    return await seed_gallery(client.db_state.session_factory, storage)


async def _set(client, g, coll: str, **values) -> None:
    with tenant_scope(DEFAULT_TENANT):
        async with client.db_state.session_factory() as s:
            stmt = update(Collection).where(Collection.slug == g.slugs[coll]).values(**values)
            await s.execute(stmt)
            await s.commit()


def _strong(tag: str) -> bool:
    return tag.startswith('"') and tag.endswith('"')


@pytest.mark.unbound_tenant
@pytest.mark.parametrize(
    ("surface", "coll", "name", "tail", "who", "want"),
    [
        ("twin", "pub", "blurred", "r/small", None, PUBLIC),
        ("twin", "pub", "blurred", "display", None, PUBLIC),
        ("twin", "pub", "plain", "original", None, PRIVATE),
        ("admin", "pub", "blurred", "r/small", STRANGER, PRIVATE),
        ("admin", "priv", "blurred", "display", OWNER, PRIVATE),
        ("admin", "priv", "plain", "original", OWNER, PRIVATE),
        ("admin", "priv", "blurred", "original", OWNER, NO_STORE),
    ],
)
async def test_every_byte_route_revalidates(client, g, surface, coll, name, tail, who, want):
    url = (g.public_url if surface == "twin" else g.url)(coll, name, tail)
    got = await client.get(url, headers=headers(who))
    assert got.status_code == 200, got.text
    assert got.headers["cache-control"] == want
    assert "immutable" not in got.headers["cache-control"]
    assert "max-age" not in got.headers["cache-control"]
    assert _strong(got.headers["etag"])


@pytest.mark.unbound_tenant
@pytest.mark.parametrize("tail", ["r/small", "display"])
async def test_a_conditional_request_is_refused_once_the_collection_goes_private(client, g, tail):
    url = g.public_url("pub", "blurred", tail)
    got = await client.get(url)
    cond = {"If-None-Match": got.headers["etag"]}
    again = await client.get(url, headers=cond)
    assert (again.status_code, again.headers["cache-control"]) == (304, PUBLIC)
    await _set(client, g, "pub", visibility=Visibility.PRIVATE)
    gone = await client.get(url, headers=cond)
    assert gone.status_code == 404
    assert "etag" not in gone.headers
    # And the admin route refuses a stranger who could read it while public.
    admin = g.url("pub", "blurred", tail)
    assert (await client.get(admin, headers={**headers(STRANGER), **cond})).status_code == 404


@pytest.mark.unbound_tenant
async def test_a_conditional_request_is_refused_once_the_image_is_withheld(client, g):
    """``protect_originals`` with no display mutator withholds the plain image:
    its rendition stops answering, 304 included."""
    url = g.public_url("pub", "plain", "r/small")
    got = await client.get(url)
    assert got.status_code == 200
    cond = {"If-None-Match": got.headers["etag"]}
    assert (await client.get(url, headers=cond)).status_code == 304
    await _set(client, g, "pub", protect_originals=True)
    gone = await client.get(url, headers=cond)
    assert gone.status_code == 404
    admin = g.url("pub", "plain", "r/small")
    viewer = await client.get(admin, headers={**headers(STRANGER), **cond})
    assert viewer.status_code == 404


async def test_the_owner_still_revalidates_a_private_image(client, g):
    url = g.url("priv", "blurred", "r/small")
    got = await client.get(url, headers=headers(OWNER))
    again = await client.get(url, headers={**headers(OWNER), "If-None-Match": got.headers["etag"]})
    assert (again.status_code, again.headers["cache-control"]) == (304, PRIVATE)
