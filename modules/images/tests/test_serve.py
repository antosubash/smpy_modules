"""``GET /api/images/images/{id}/r/{size}``, ``…/display`` and ``…/original`` (Task 12).

Access first, then the cache headers, then the 304 or the bytes: a request the
policy refuses learns nothing, and a 304 carries the same ``Cache-Control`` and
``ETag`` the full answer would have.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from tests.access_support import EDITOR, MANAGER, OWNER, STRANGER, headers
from tests.serve_support import seed_gallery
from tests.stub_auth import as_user

PRIVATE = "private, max-age=3600"
NO_STORE = "private, no-store"
ORIGINALS = as_user("orla", ("images.view", "images.originals.view"))


@pytest_asyncio.fixture
async def g(client, storage):
    return await seed_gallery(client.db_state.session_factory, storage)


async def get(client, url, who=OWNER, **hdrs):
    return await client.get(url, headers={**headers(who), **hdrs})


async def test_owner_gets_rendition_bytes_with_private_cache_and_strong_etag(client, g):
    got = await get(client, g.url("priv", "plain", "r/small"))
    assert got.status_code == 200, got.text
    assert got.content == g.bytes["priv.plain.small"]
    assert got.headers["content-type"] == "image/jpeg"
    assert got.headers["cache-control"] == PRIVATE
    assert got.headers["x-content-type-options"] == "nosniff"
    etag = got.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"') and not etag.startswith("W/")
    # The key is generation-specific; the tag never spells it out.
    assert str(g.ids["priv.plain"]) not in etag


async def test_if_none_match_is_a_304_with_the_same_headers(client, g):
    url = g.url("priv", "plain", "r/small")
    first = await get(client, url)
    again = await get(client, url, **{"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == first.headers["etag"]
    assert again.headers["cache-control"] == PRIVATE
    star = await get(client, url, **{"If-None-Match": '"other", *'})
    assert star.status_code == 304
    miss = await get(client, url, **{"If-None-Match": '"other"'})
    assert miss.status_code == 200


async def test_each_object_has_its_own_etag(client, g):
    tags = {
        (await get(client, g.url("priv", "blurred", tail))).headers["etag"]
        for tail in ("r/small", "display", "original")
    }
    assert len(tags) == 3


@pytest.mark.parametrize("tail", ["r/small", "display", "original"])
async def test_a_stranger_gets_the_404_of_an_absent_id(client, g, tail):
    got = await get(client, g.url("priv", "plain", tail), who=STRANGER)
    assert got.status_code == 404
    absent = await get(client, f"/api/images/images/{uuid.uuid4()}/{tail}", who=STRANGER)
    assert (absent.status_code, absent.json()) == (404, got.json())
    assert g.bytes["priv.plain.original"] not in got.content


@pytest.mark.parametrize("tail", ["r/small", "display", "original"])
async def test_the_anonymous_are_refused_on_the_admin_surface(client, g, tail):
    got = await client.get(g.url("priv", "plain", tail))
    assert got.status_code == 401


async def test_unknown_size_is_404(client, g):
    got = await get(client, g.url("priv", "plain", "r/huge"))
    assert got.status_code == 404


async def test_display_is_the_display_copy_or_the_original(client, g):
    blurred = await get(client, g.url("priv", "blurred", "display"))
    assert blurred.content == g.bytes["priv.blurred.display"]
    plain = await get(client, g.url("priv", "plain", "display"))
    assert plain.content == g.bytes["priv.plain.original"]
    assert plain.headers["cache-control"] == PRIVATE


async def test_protected_original_is_403_to_an_edit_share(client, g):
    got = await get(client, g.url("priv", "blurred", "original"), who=EDITOR)
    assert got.status_code == 403
    assert g.bytes["priv.blurred.original"] not in got.content
    # ...and to images.manage alone, which is not images.originals.view
    assert (await get(client, g.url("priv", "blurred", "original"), who=MANAGER)).status_code == 403
    # The share still sees the display copy and the unprotected original.
    assert (await get(client, g.url("priv", "blurred", "display"), who=EDITOR)).status_code == 200
    assert (await get(client, g.url("priv", "plain", "original"), who=EDITOR)).status_code == 200


async def test_protected_original_is_no_store_even_for_the_owner(client, g):
    url = g.url("priv", "blurred", "original")
    got = await get(client, url)
    assert got.status_code == 200
    assert got.content == g.bytes["priv.blurred.original"]
    assert got.headers["cache-control"] == NO_STORE
    again = await get(client, url, **{"If-None-Match": got.headers["etag"]})
    assert (again.status_code, again.headers["cache-control"]) == (304, NO_STORE)


async def test_originals_permission_opens_a_protected_original(client, g):
    got = await client.get(g.url("pub", "blurred", "original"), headers=ORIGINALS)
    assert got.status_code == 200
    assert got.headers["cache-control"] == NO_STORE


async def test_the_admin_route_is_never_shareable_even_for_a_public_collection(client, g):
    for tail in ("r/small", "display"):
        got = await get(client, g.url("pub", "plain", tail), who=STRANGER)
        assert got.status_code == 200
        assert got.headers["cache-control"] == PRIVATE


async def test_range_on_display_and_original(client, g):
    for tail, key in (("display", "priv.blurred.display"), ("original", "priv.plain.original")):
        name = "blurred" if "blurred" in key else "plain"
        got = await get(client, g.url("priv", name, tail), Range="bytes=10-19")
        assert got.status_code == 206, got.text
        size = len(g.bytes[key])
        assert got.content == g.bytes[key][10:20]
        assert got.headers["content-range"] == f"bytes 10-19/{size}"
        assert got.headers["content-length"] == "10"
        assert got.headers["accept-ranges"] == "bytes"
        assert got.headers["cache-control"] == PRIVATE
        whole = await get(client, g.url("priv", name, tail))
        assert whole.headers["accept-ranges"] == "bytes"
        assert whole.headers["content-length"] == str(size)


async def test_suffix_range_and_unsatisfiable_range(client, g):
    data = g.bytes["priv.blurred.display"]
    tail = await get(client, g.url("priv", "blurred", "display"), Range="bytes=-5")
    assert (tail.status_code, tail.content) == (206, data[-5:])
    past = await get(client, g.url("priv", "blurred", "display"), Range=f"bytes={len(data)}-")
    assert past.status_code == 416
    assert past.headers["content-range"] == f"bytes */{len(data)}"


async def test_a_stale_if_range_serves_the_whole_object(client, g):
    url = g.url("priv", "blurred", "display")
    got = await get(client, url, Range="bytes=0-3", **{"If-Range": '"stale"'})
    assert got.status_code == 200
    assert got.content == g.bytes["priv.blurred.display"]
    tag = got.headers["etag"]
    fresh = await get(client, url, Range="bytes=0-3", **{"If-Range": tag})
    assert fresh.status_code == 206


async def test_a_protected_original_refuses_before_any_range_or_304(client, g):
    url = g.url("priv", "blurred", "original")
    tag = (await get(client, url)).headers["etag"]
    for extra in ({"If-None-Match": tag}, {"Range": "bytes=0-3"}):
        got = await get(client, url, who=EDITOR, **extra)
        assert got.status_code == 403
        assert "etag" not in got.headers


async def test_a_missing_object_is_404_not_500(client, g, storage):
    await storage.delete(g.keys["priv.plain.small"])
    got = await get(client, g.url("priv", "plain", "r/small"))
    assert got.status_code == 404
    assert got.json() == (await get(client, g.url("priv", "plain", "r/huge"))).json()
