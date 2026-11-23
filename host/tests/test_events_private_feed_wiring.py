"""Private feed links in the real host: the route, its exemption and budget, the cleanup."""

from __future__ import annotations

import asyncio

from test_events_booted import booted_host  # noqa: F401 - the shared fixture

TOKEN = f"evf_{'0' * 43}"


def test_private_feed_wired_by_startup(booted_host, monkeypatch):  # noqa: F811
    """A link nobody holds is public to ``GET``/``HEAD`` (the token is the credential), has its
    own budget, and gets one answer however it is malformed."""
    from fastapi.routing import iter_route_contexts
    from httpx import ASGITransport, AsyncClient
    from simple_module_hosting.public_access import is_public

    app = booted_host

    async def setup_done(_app) -> bool:
        return True

    monkeypatch.setattr(app.state.sm.setup_registry, "is_setup_complete", setup_done)

    async def exercise() -> dict:
        async with app.router.lifespan_context(app):
            paths = {c.path for c in iter_route_contexts(app.routes)}
            rate = getattr(
                app.state.rate_limit_rules.match("GET", "/events/feed/evf_x.ics"), "rate", None
            )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://localhost"
            ) as http:
                return {
                    "paths": paths,
                    "rate": rate,
                    "exempt": is_public(app, "GET", "/events/feed/evf_x.ics"),
                    "unknown": await http.get(f"/events/feed/{TOKEN}.ics"),
                    "malformed": await http.get("/events/feed/not-a-token.ics"),
                    "head": await http.head(f"/events/feed/{TOKEN}.ics"),
                }

    got = asyncio.run(exercise())
    assert "/events/feed/{token}.ics" in got["paths"]
    assert got["exempt"] is True and got["rate"] == "30/minute"
    for refused in (got["unknown"], got["malformed"]):
        assert refused.status_code == 404, refused.text[:300]
        assert refused.json() == {"detail": "Not found", "code": "not_found"}
        assert refused.headers["cache-control"] == "no-store"
        assert "etag" not in refused.headers
        # The route sends ``no-referrer`` (its own tests pin that), but the framework's
        # SecurityHeadersMiddleware replaces ``Referrer-Policy`` on every response, so a real
        # host answers its own value. Pinned so a framework change either way is noticed.
        assert refused.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert got["head"].status_code == 404 and got["head"].content == b""


def test_feed_token_cleanup_is_subscribed(booted_host):  # noqa: F811
    """The real host gives events the bus, so a deleted user, membership or tenant takes its
    private feed links with it."""
    from simple_module_core.tenant_events import TenantDeleted
    from simple_module_core.user_events import UserDeleted
    from tenants.contracts.events import MembershipRemoved

    bus = booted_host.state.sm.event_bus
    for event in (UserDeleted, MembershipRemoved, TenantDeleted):
        modules = [
            getattr(h, "__module__", "") for h in bus._emitter.listeners(bus._event_key(event))
        ]
        assert "sm_events.feeds.tokens.cleanup" in modules, (event.__name__, modules)
