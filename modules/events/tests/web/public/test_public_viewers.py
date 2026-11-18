"""What a public page says does not depend on who asks, and names no event's id."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.dependencies.utils import get_dependant
from fastapi.routing import APIRoute
from sm_events.web.endpoints.public import _urls, alias_router, public_router

from tests.support.app import as_user
from tests.support.calendars import PublicFixture
from tests.support.public import INERTIA, seed_public
from tests.web.public.leaks import LOCALES, _api_url

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@pytest.fixture
async def fx(public_locales_client) -> PublicFixture:
    return await seed_public(public_locales_client)


def _public_addresses(fx: PublicFixture, locale: str) -> list[str]:
    pages = [
        fx.one_off,
        fx.series,
        fx.conf,
        fx.talk,
        fx.orphan,
    ]  # a parent with a draft child, a child with a draft parent
    return [
        *[_urls.event_path(fx.slug(e, locale), locale) for e in pages],
        *[_urls.event_ics_path(fx.slug(e, locale), locale) for e in pages],
        _urls.index_path(locale),
        _urls.calendar_path(fx.pub.slug, locale),
        _urls.calendar_ics_path(fx.pub.slug, locale),
        _urls.calendar_ics_path(None, locale),
        _urls.sitemap_path(),
        _api_url(locale),
    ]


async def test_a_signed_in_manager_sees_the_anonymous_bytes_on_public_pages(
    public_locales_client, fx
):
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    for locale in LOCALES:
        for url in _public_addresses(fx, locale):
            anon = await public_locales_client.get(url, headers=INERTIA)
            signed = await public_locales_client.get(url, headers=INERTIA | manager)
            assert anon.status_code == signed.status_code == 200, url
            if "x-inertia" in anon.headers:
                assert signed.json()["props"] == anon.json()["props"], url
            assert signed.content == anon.content, url
            assert signed.headers.get("content-type") == anon.headers.get("content-type"), url


async def test_no_public_json_names_an_event_id(public_locales_client, fx):
    """Event ids stay out of the page props, the sub-events' keys and the occurrences API (the
    ids of public calendars and categories are the grid's filter inputs, so they stay)."""
    ids = {str(e.id) for e in [*fx.public_events, *fx.hidden.values()]}
    public_ids = {str(fx.pub.id), str(fx.public_cat.id)}
    seen = 0
    for locale in LOCALES:
        for url in _public_addresses(fx, locale):
            if url.endswith((".ics", ".xml")):
                continue
            got = await public_locales_client.get(url, headers=INERTIA)
            text = json.dumps(got.json())
            seen += 1
            assert not any(i in text for i in ids), url
            assert set(UUID.findall(text)) <= public_ids, url
    assert seen == 16


_IDENTITY = ("user", "principal", "permission", "auth", "session", "csrf", "login", "token")
_LANGUAGES = ("en", "de")


def _calls_of(dependant):
    """Every callable a dependant pulls in, itself and everything under it."""
    yield dependant.call
    for dep in dependant.dependencies:
        yield from _calls_of(dep)


def _walk(router, inherited=()):
    """``(path, route, dependencies from every router above it)`` for each handler of a router,
    following ``include_router`` (this FastAPI keeps an include as a node of its own)."""
    own = (*inherited, *(getattr(router, "dependencies", None) or ()))
    for route in router.routes:
        if hasattr(route, "include_context"):
            deps = (*own, *route.include_context.dependencies)
            yield from _walk(route.original_router, deps)
        elif isinstance(route, APIRoute):
            yield route.path, route, (*own, *route.dependencies)


def _named(call) -> str:
    return f"{getattr(call, '__module__', '')}.{getattr(call, '__qualname__', repr(call))}".lower()


def test_no_public_route_depends_on_who_is_asking(public_locales_client):
    """By signature, not by grep: no handler of a public router, and nothing its ``Depends`` pulls
    in, takes a user, a principal, a permission check, a session or a CSRF token. Only the cache
    policy (``_cache.py``) looks at who is signed in, to refuse to keep their copy."""
    routers = (*[public_router(language) for language in _LANGUAGES], alias_router("/events"))
    found = [item for router in routers for item in _walk(router)]
    assert len(found) >= 14, len(found)
    seen: set[str] = set()
    for path, route, depends in found:
        calls = [*_calls_of(route.dependant)]
        for depend in depends:
            calls.extend(_calls_of(get_dependant(path="", call=depend.dependency)))
        for call in calls:
            name = _named(call)
            seen.add(name)
            assert not any(word in name for word in _IDENTITY), (path, name)
        for param in route.dependant.query_params + route.dependant.header_params:
            assert not any(word in param.name.lower() for word in _IDENTITY), (path, param.name)
        for name, annotation in route.dependant.call.__annotations__.items():
            text = f"{name} {annotation}".lower()
            assert not any(word in text for word in ("principal", "user", "permission")), (
                path,
                text,
            )
    # The check is not vacuous: it sees the dependencies it is about.
    assert any("bind_public" in n for n in seen) and any("public_tenant" in n for n in seen)
