"""MISSING 2: the anonymous read API is cacheable.

`GET {public_route_prefix}/…` is the one surface with no session behind it and
it sent neither `ETag` nor `Cache-Control`, so every anonymous reader was a
full page build and a full body. `updated_at`/`published_at` are on the row
already, so a validator is nearly free.

What the tests pin is the pair: the same content gives the same validator, a
*different* content gives a different one, and a conditional GET that matches
is a `304` with no body. `public_cache_seconds = 0` is the opt-out, for an
install whose "published" means "visible the instant it is saved".

Upstream note, deliberately not worked around here: on a real host every
anonymous response also carries `Vary: Cookie` and a fresh
`Set-Cookie: session=…`, written by
`simple_module_hosting/_inertia_shared.py:54` on every request. A response
carrying `Set-Cookie` is not storable by a *shared* cache, so these headers
help a browser and a private cache until that is fixed. This module never
touches `request.session`; the harness does not run that middleware, which is
why it is not visible here.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, api_record, api_type, roles

_API = "/api/records/types"
_PUBLIC = "/api/records/public"
_FIELDS = [{"key": "name", "type": "text", "label": "Name", "indexed": True}]


async def _type(client, key: str) -> dict:
    return await api_type(client, key, _FIELDS, display_field="name", is_public=True)


async def _record(client, key: str, name: str) -> dict:
    return await api_record(client, key, {"name": name}, status="published")


async def test_a_public_listing_carries_an_etag_and_a_cache_policy(public_client):
    await _type(public_client, "cachelist")
    await _record(public_client, "cachelist", "one")
    resp = await public_client.get(f"{_PUBLIC}/cachelist")
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "public, max-age=60"
    assert resp.headers["etag"].startswith('W/"')


async def test_a_public_record_read_carries_them_too(public_client):
    await _type(public_client, "cacheone")
    created = await _record(public_client, "cacheone", "only")
    resp = await public_client.get(f"{_PUBLIC}/cacheone/{created['uuid']}")
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "public, max-age=60"
    assert resp.headers["etag"].startswith('W/"')


async def test_a_conditional_get_that_matches_is_a_304_with_no_body(public_client):
    await _type(public_client, "cache304")
    await _record(public_client, "cache304", "one")
    first = await public_client.get(f"{_PUBLIC}/cache304")
    tag = first.headers["etag"]

    again = await public_client.get(f"{_PUBLIC}/cache304", headers={"If-None-Match": tag})
    assert again.status_code == 304, again.text
    assert again.content == b""
    # A cache refreshing an entry learns the freshness lifetime from this
    # response and no other, so both headers have to travel with the 304.
    assert again.headers["etag"] == tag
    assert again.headers["cache-control"] == "public, max-age=60"


async def test_a_star_or_a_stripped_weak_prefix_still_matches(public_client):
    """``If-None-Match`` comparison is weak, and ``*`` matches anything."""
    await _type(public_client, "cacheweak")
    await _record(public_client, "cacheweak", "one")
    tag = (await public_client.get(f"{_PUBLIC}/cacheweak")).headers["etag"]

    for header in ("*", tag.removeprefix("W/"), f'"deadbeef", {tag}'):
        resp = await public_client.get(f"{_PUBLIC}/cacheweak", headers={"If-None-Match": header})
        assert resp.status_code == 304, (header, resp.text)


async def test_the_validator_changes_when_the_content_does(public_client):
    await _type(public_client, "cachechange")
    await _record(public_client, "cachechange", "one")
    before = (await public_client.get(f"{_PUBLIC}/cachechange")).headers["etag"]

    await _record(public_client, "cachechange", "two")
    after = await public_client.get(f"{_PUBLIC}/cachechange", headers={"If-None-Match": before})
    assert after.status_code == 200, after.text
    assert after.headers["etag"] != before


async def test_a_different_query_is_a_different_validator(public_client):
    await _type(public_client, "cachequery")
    await _record(public_client, "cachequery", "alpha")
    await _record(public_client, "cachequery", "beta")
    everything = (await public_client.get(f"{_PUBLIC}/cachequery")).headers["etag"]
    filtered = await public_client.get(
        f"{_PUBLIC}/cachequery?filter=name:eq:alpha", headers={"If-None-Match": everything}
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.headers["etag"] != everything


async def test_zero_seconds_is_no_store_and_no_validator(public_client):
    public_client.app.state.sm_records.settings.public_cache_seconds = 0
    await _type(public_client, "cacheoff")
    await _record(public_client, "cacheoff", "one")
    resp = await public_client.get(f"{_PUBLIC}/cacheoff")
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    assert "etag" not in resp.headers


async def test_a_head_request_carries_the_headers_too(public_client):
    await _type(public_client, "cachehead")
    await _record(public_client, "cachehead", "one")
    resp = await public_client.head(f"{_PUBLIC}/cachehead")
    assert resp.status_code == 200, resp.text
    assert resp.headers["etag"].startswith('W/"')
    assert resp.headers["cache-control"] == "public, max-age=60"


async def test_the_admin_api_is_untouched(public_client):
    """Per-caller responses; the framework already forces those private."""
    await _type(public_client, "cacheadmin")
    resp = await public_client.get(f"{_API}/cacheadmin/records", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    assert "etag" not in resp.headers
    assert "cache-control" not in resp.headers
