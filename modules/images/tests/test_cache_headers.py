"""``sm_images.cache``: the one place an image response's caching is decided.

Shareable needs all four: a public collection, a rendition or display copy,
the public twin, and a tenant nothing request-specific chose (records #196).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from sm_images import cache
from sm_images.models import Visibility
from sm_images.tenancy import DEFAULT_TENANT, configure, note_tenant_source, tenant_scope
from starlette.requests import Request

from tests.access_support import collection

# Each test binds (or not) the tenant contextvar itself: a binding is one of
# the request-specific sources ``note_tenant_source`` records.
pytestmark = pytest.mark.unbound_tenant

SHARED = "public, max-age=31536000, immutable"
PRIVATE = "private, max-age=3600"
NO_STORE = "private, no-store"


def _request(tenant: str | None = None) -> Request:
    app = FastAPI()
    configure(app)
    req = Request({"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"})
    if tenant is not None:
        req.state.tenant_id = tenant
    note_tenant_source(req)  # what ``bind_public`` records before its fallback
    return req


def _cc(req, coll, route, **kw):
    return cache.cache_headers(req, coll, route, **{"current": True, **kw})


@pytest.mark.parametrize("route", [cache.RENDITION, cache.DISPLAY])
def test_public_twin_rendition_and_display_are_shareable(route):
    coll = collection("p", Visibility.PUBLIC)
    assert _cc(_request(), coll, route, twin=True) == SHARED


@pytest.mark.parametrize("visibility", [Visibility.PRIVATE, Visibility.INTERNAL])
def test_a_non_public_collection_is_private(visibility):
    coll = collection("p", visibility)
    assert _cc(_request(), coll, cache.RENDITION, twin=True) == PRIVATE


def test_the_admin_route_is_private_for_a_public_collection():
    coll = collection("p", Visibility.PUBLIC)
    assert _cc(_request(), coll, cache.DISPLAY, twin=False) == PRIVATE


def test_an_original_is_never_shareable():
    coll = collection("p", Visibility.PUBLIC)
    assert _cc(_request(), coll, cache.ORIGINAL, twin=True) == PRIVATE


@pytest.mark.parametrize("twin", [True, False])
def test_a_protected_original_is_no_store(twin):
    coll = collection("p", Visibility.PUBLIC)
    assert _cc(_request(), coll, cache.ORIGINAL, twin=twin, protected=True) == NO_STORE


def test_an_upstream_tenant_is_private():
    coll = collection("p", Visibility.PUBLIC)
    assert _cc(_request("acme"), coll, cache.RENDITION, twin=True) == PRIVATE


def test_the_default_tenant_named_upstream_is_request_specific_so_private():
    """Records #196: what matters is who chose the tenant, not its value."""
    coll = collection("p", Visibility.PUBLIC)
    assert _cc(_request("default"), coll, cache.RENDITION, twin=True) == PRIVATE


def test_a_request_bind_public_never_saw_fails_closed():
    app = FastAPI()
    configure(app)
    req = Request({"type": "http", "app": app, "headers": [], "path": "/", "method": "GET"})
    coll = collection("p", Visibility.PUBLIC)
    assert _cc(req, coll, cache.RENDITION, twin=True) == PRIVATE


@pytest.mark.parametrize(
    ("twin", "want"), [(True, "public, no-cache"), (False, "private, no-cache")]
)
def test_a_url_not_naming_the_current_bytes_is_no_cache(twin, want):
    coll = collection("p", Visibility.PUBLIC)
    for route in (cache.RENDITION, cache.DISPLAY):
        assert _cc(_request(), coll, route, twin=twin, current=False) == want


def test_a_non_public_stale_url_is_private_no_cache():
    coll = collection("p", Visibility.PRIVATE)
    assert _cc(_request(), coll, cache.DISPLAY, twin=True, current=False) == "private, no-cache"


def test_the_version_is_generation_and_key_digest():
    v = cache.version(3, "images/t/c/i/display.3.x.jpg")
    gen, digest = v.split(".")
    assert gen == "3" and len(digest) == 12 and "images" not in v
    assert v != cache.version(3, "images/t/c/i/display.3.y.jpg")


def test_etag_is_strong_and_depends_on_key_and_size():
    a = cache.etag("images/t/c/i/r/small.1.x.jpg", 10)
    assert a.startswith('"') and a.endswith('"')
    assert a == cache.etag("images/t/c/i/r/small.1.x.jpg", 10)
    assert a != cache.etag("images/t/c/i/r/small.1.y.jpg", 10)
    assert a != cache.etag("images/t/c/i/r/small.1.x.jpg", 11)
    assert "images/" not in a


@pytest.mark.parametrize(
    ("header", "hit"),
    [(None, False), ("", False), ("*", True), ("TAG", True), ('"x", TAG', True), ("W/TAG", True)],
)
def test_if_none_match(header, hit):
    tag = cache.etag("k", 1)
    sent = None if header is None else header.replace("TAG", tag)
    assert cache.not_modified(sent, tag) is hit


def test_a_context_bound_default_with_no_request_state_is_not_shareable():
    coll = collection("p", Visibility.PUBLIC)
    with tenant_scope(DEFAULT_TENANT):
        req = _request()
    assert _cc(req, coll, cache.RENDITION, twin=True) == PRIVATE
