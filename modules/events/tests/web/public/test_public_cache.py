"""Cache policy: who may share an answer, for how long, and the validators."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from simple_module_hosting.middleware import TenantMiddleware
from sm_events.core.errors import NotFound, install_exception_handlers
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import TenancyMode
from sm_events.web.endpoints.public import _cache, _errors
from sm_events.web.endpoints.public._tenant import public_tenant
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = pytest.mark.unbound_tenant

ETAG = 'W/"abc"'


class _Upstream(BaseHTTPMiddleware):
    """What an auth layer and a tenant resolver in front of the module would do."""

    async def dispatch(self, request, call_next):
        if tenant := request.headers.get("x-up"):
            request.state.tenant_id = tenant
        if request.headers.get("x-user"):
            request.state.user = SimpleNamespace(id=request.headers["x-user"])
        return await call_next(request)


def make_app(
    *,
    mode: TenancyMode = TenancyMode.SINGLE,
    header: str | None = None,
    seconds: int = 300,
    origin: str = "https://example.org",
) -> FastAPI:
    app = FastAPI()
    settings = EventsSettings(public_cache_seconds=seconds)
    app.state.sm_events = SimpleNamespace(tenancy=mode, settings=settings)
    app.state.sm = SimpleNamespace(settings=SimpleNamespace(public_base_url=origin))
    install_exception_handlers(app)
    if mode is TenancyMode.MULTI:
        app.add_middleware(TenantMiddleware, header=header)
    app.add_middleware(_Upstream)
    router = APIRouter(route_class=_errors.PublicErrorRoute, dependencies=[Depends(public_tenant)])

    @router.get("/p/{kind}")
    async def page(request: Request, kind: str):
        response = Response("body")
        return _cache.apply(response, request, settings, kind=kind, etag=ETAG)  # type: ignore[arg-type]

    @router.get("/conditional")
    async def conditional(request: Request):
        response = _cache.apply(Response("body"), request, settings, kind="page", etag=ETAG)
        return _cache.not_modified(request, response.headers) or response

    @router.get("/missing")
    async def missing():
        raise NotFound

    @router.get("/number/{n}")
    async def number(n: int):
        return n

    @router.get("/rendered-404")
    async def rendered():
        return Response("gone", status_code=404, headers={"ETag": ETAG})

    app.include_router(router)
    return app


async def get(app: FastAPI, path: str, **headers: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        return await http.get(path, headers=headers)


def vary(response) -> list[str]:
    return [v.strip() for v in response.headers.get("vary", "").split(",") if v.strip()]


async def test_single_default_is_public():
    app = make_app()
    page = await get(app, "/p/page")
    assert page.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=60"
    assert page.headers["etag"] == ETAG
    assert (await get(app, "/p/listing")).headers["cache-control"] == "public, max-age=60"
    assert (await get(app, "/p/api")).headers["cache-control"] == "public, max-age=60"
    for kind in ("feed", "sitemap"):
        assert (await get(app, f"/p/{kind}")).headers["cache-control"] == "public, max-age=300"


async def test_short_lifetimes_are_capped_by_the_setting():
    app = make_app(seconds=30)
    assert (await get(app, "/p/listing")).headers["cache-control"] == "public, max-age=30"
    assert (await get(app, "/p/feed")).headers["cache-control"] == "public, max-age=30"


@pytest.mark.parametrize(
    "case",
    ["upstream_default", "upstream_other", "multi_header", "multi_none"],
)
async def test_request_tenant_never_shareable(case):
    header = "X-Tenant"
    if case == "upstream_default":
        app, headers = make_app(), {"x-up": "default"}
    elif case == "upstream_other":
        app, headers = make_app(), {"x-up": "acme"}
    elif case == "multi_header":
        app, headers = make_app(mode=TenancyMode.MULTI, header=header), {"x-tenant": "acme"}
    else:
        app, headers = make_app(mode=TenancyMode.MULTI, header=header), {}
    got = await get(app, "/p/feed", **headers)
    assert got.status_code == 200
    assert got.headers["cache-control"] == "private, max-age=300"
    # As news does: a tenant someone else picked varies on the session, in whatever mode the
    # stack was detected (a single-tenant app under a multi-tenant parent included).
    assert "Cookie" in vary(got)
    if case.startswith("multi"):
        assert {"Cookie", header} <= set(vary(got))


async def test_private_single_names_the_tenant_header_when_there_is_one():
    app = make_app(header="X-Tenant")  # a single-tenant stack with a header configured
    app.add_middleware(TenantMiddleware, header="X-Tenant", fixed="default")
    app.state.sm_events.tenancy = TenancyMode.SINGLE
    got = await get(app, "/p/feed", **{"x-up": "default"})
    assert got.headers["cache-control"].startswith("private")
    assert "X-Tenant" in vary(got)


async def test_signed_in_page_is_private_no_store_without_etag():
    app = make_app()
    for kind in ("page", "listing"):
        got = await get(app, f"/p/{kind}", **{"x-user": "u1"})
        assert got.headers["cache-control"] == "private, no-store"
        assert "etag" not in got.headers
    # Machine-read kinds hold no user, so the visitor's session changes nothing.
    got = await get(app, "/p/feed", **{"x-user": "u1"})
    assert got.headers["cache-control"] == "public, max-age=300" and "etag" in got.headers


@pytest.mark.parametrize("kind", ["page", "listing", "feed", "sitemap", "api"])
async def test_zero_seconds_is_no_store(kind):
    got = await get(make_app(seconds=0), f"/p/{kind}")
    assert got.headers["cache-control"] == "no-store"
    assert "etag" not in got.headers


async def test_vary_per_viewer_and_host():
    page = await get(make_app(), "/p/page")
    assert vary(page) == ["X-Inertia", "Cookie", "Accept-Language"]
    feed = await get(make_app(), "/p/feed")
    assert vary(feed) == []
    guessed = make_app(origin="")
    assert vary(await get(guessed, "/p/feed")) == ["Host"]
    assert vary(await get(guessed, "/p/page")) == ["X-Inertia", "Cookie", "Accept-Language", "Host"]


@pytest.mark.parametrize("sent", [ETAG, '"abc"', f'"x", {ETAG}', "*"])
async def test_not_modified_keeps_headers(sent):
    got = await get(make_app(), "/conditional", **{"if-none-match": sent})
    assert got.status_code == 304 and got.content == b""
    assert got.headers["etag"] == ETAG
    assert got.headers["cache-control"].startswith("public, max-age=300")
    assert "Accept-Language" in vary(got)
    assert "content-security-policy" not in got.headers


async def test_a_different_tag_is_a_full_response():
    got = await get(make_app(), "/conditional", **{"if-none-match": 'W/"other"'})
    assert got.status_code == 200 and got.text == "body"


async def test_error_route_no_store():
    app = make_app(mode=TenancyMode.MULTI, header="X-Tenant")
    for path in ("/missing", "/number/x", "/rendered-404"):
        got = await get(app, path, **{"x-tenant": "acme"})
        assert got.status_code in (404, 422), path
        assert got.headers["cache-control"] == "no-store", path
        assert "etag" not in got.headers, path
        assert {"Cookie", "X-Tenant"} <= set(vary(got)), path
    single = await get(make_app(), "/missing")
    assert single.headers["cache-control"] == "no-store" and vary(single) == []


async def test_errors_are_identical_whatever_the_cause():
    """The oracle rule at the policy level: one code path, one set of headers."""
    app = make_app()
    first, second = await get(app, "/missing"), await get(app, "/rendered-404")
    assert dict(first.headers).keys() >= {"cache-control"}
    assert first.headers["cache-control"] == second.headers["cache-control"]
    assert vary(first) == vary(second)


def test_page_etag_varies():
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    base = {"variant": "html", "viewer": "en:anon"}

    def tag(*parts, **kw):
        return _cache.page_etag(*parts, **{**base, **kw})

    reference = tag("e1", 3, stamp, "en")
    assert reference == tag("e1", 3, stamp, "en")
    assert reference.startswith('W/"') and len(reference) == len('W/"') + 16 + 1
    for other in (
        tag("e2", 3, stamp, "en"),
        tag("e1", 4, stamp, "en"),
        tag("e1", 3, datetime(2026, 1, 2, tzinfo=UTC), "en"),
        tag("e1", 3, stamp, "de"),
        tag("e1", 3, stamp, "en", variant="inertia"),
        tag("e1", 3, stamp, "en", viewer="de:anon"),
    ):
        assert other != reference


def test_part_boundaries_are_not_ambiguous():
    assert _cache.page_etag("a", "bc", variant="v", viewer="w") != _cache.page_etag(
        "ab", "c", variant="v", viewer="w"
    )


def test_body_etag():
    one, two = _cache.body_etag(b"x"), _cache.body_etag(b"y")
    assert one != two and one == _cache.body_etag(b"x")
    assert one.startswith('W/"') and len(one) == len('W/"') + 32 + 1


def test_viewer_key_never_holds_the_raw_id():
    request = SimpleNamespace(
        state=SimpleNamespace(user=SimpleNamespace(id="secret-id"), locale="de")
    )
    key = _cache.viewer_key(request)  # type: ignore[arg-type]
    assert key.startswith("de:u:") and "secret-id" not in key
    anon = SimpleNamespace(state=SimpleNamespace(locale=None))
    assert _cache.viewer_key(anon) == ":anon"  # type: ignore[arg-type]
