"""The leak harness: everything that must never reach an anonymous visitor.

Every public route is added to :func:`surfaces`, and every test below walks that table, so a
new surface is covered the day it exists. A surface is one of

* ``kind="page"``: the address of *one event* on that surface (its page, its ``.ics``, ...).
  For a hidden event it must be the 404, in every language it could be asked for;
* ``kind="listing"``: an address that lists events (the index, a calendar's page and feed, the
  occurrences API, the sitemap, the 404's suggestions). The body must hold none of a hidden
  event's title, slug or UID.

What is hidden (:data:`HIDDEN`): a draft, an in-review and a scheduled event of a public
calendar, a published event of an internal and of a private calendar, a trashed event, and a
published event of a trashed calendar. Plus, in ``seed_public_fixture``, a draft sub-event and
a draft parent. The rules these pin are the module's Review Focus:

1. a hidden event is absent from every listing and its own addresses are the 404;
2. a hidden calendar's addresses are the 404;
3. another tenant's rows are absent, and a request that resolved no tenant is the 404;
4. an unknown, hidden and trashed target are indistinguishable (status, props, cache headers);
5. a signed-in manager sees exactly what an anonymous visitor sees.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sm_events.web.endpoints.public import _urls

from tests.support.app import as_user
from tests.support.calendars import PublicFixture
from tests.support.public import INERTIA, seed_public, tenant_header
from tests.web.public.leaks import (
    HIDDEN,
    HIDDEN_CALENDARS,
    LOCALES,
    assert_absent,
    surfaces,
)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    """The fixture's events are in 2026; the feeds' window is around "now"."""
    from datetime import UTC, datetime

    from sm_events.web.endpoints.public import _feeds

    monkeypatch.setattr(_feeds, "utcnow", lambda: datetime(2026, 4, 1, tzinfo=UTC))


@pytest.fixture
async def fx(public_locales_client) -> PublicFixture:
    return await seed_public(public_locales_client)


def test_the_listing_check_can_fail(fx):
    """The check a listing surface uses is not vacuous: it passes on a clean body and fails
    on a leaked slug, title or UID."""
    assert_absent("<p>Nothing to see</p>", fx)
    draft = fx.hidden["draft"]
    for leaked in (fx.slug(draft), fx.slug(draft).title(), draft.uid, fx.slug(draft, "de")):
        with pytest.raises(AssertionError):
            assert_absent(f"<a>{leaked}</a>", fx)


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("hidden", HIDDEN)
async def test_hidden_event_absent_everywhere(public_locales_client, fx, hidden, locale):
    for surface in surfaces(fx, locale):
        if surface.kind == "page":
            for method in ("GET", "HEAD"):
                got = await public_locales_client.request(
                    method, surface.url(fx, locale, hidden), headers=INERTIA
                )
                assert got.status_code == 404, (surface.name, method)
                assert got.headers["cache-control"] == "no-store", surface.name
                assert "etag" not in got.headers, surface.name
        else:
            got = await public_locales_client.get(surface.url(fx, locale, None), headers=INERTIA)
            assert got.status_code == 200, surface.name
            assert_absent(got.text, fx)


@pytest.mark.parametrize("hidden", ["secret_talk", "draft_parent"])
async def test_hidden_relatives_are_hidden_too(public_locales_client, fx, hidden):
    """A draft sub-event and a draft parent: their own address is the 404."""
    path = _urls.event_path(fx.slug(fx.hidden[hidden]), "en")
    assert (await public_locales_client.get(path, headers=INERTIA)).status_code == 404


@pytest.mark.parametrize("hidden", HIDDEN_CALENDARS)
async def test_hidden_calendar_404(public_locales_client, fx, hidden):
    calendar = {"internal": fx.internal, "private": fx.private, "trashed": fx.gone}[hidden]
    for locale in LOCALES:
        for url in (
            _urls.calendar_path(calendar.slug, locale),
            _urls.calendar_ics_path(calendar.slug, locale),
        ):
            got = await public_locales_client.get(url, headers=INERTIA)
            assert got.status_code == 404, (hidden, url)
            assert got.headers["cache-control"] == "no-store"
            assert "etag" not in got.headers


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("hidden", [*HIDDEN, "secret_talk", "draft_parent"])
async def test_not_found_indistinguishable(public_locales_client, fx, hidden, locale):
    """A hidden event's address answers exactly as a slug that never existed: status, props,
    and every cache header. Nothing tells a visitor which drafts exist."""
    missing = await public_locales_client.get(
        _urls.event_path("no-such-slug", locale), headers=INERTIA
    )
    slug = fx.slug(
        fx.hidden[hidden], locale if f"{fx.hidden[hidden].id}:{locale}" in fx.slugs else "en"
    )
    got = await public_locales_client.get(_urls.event_path(slug, locale), headers=INERTIA)
    assert got.status_code == missing.status_code == 404
    assert got.json()["component"] == missing.json()["component"]
    assert got.json()["props"] == missing.json()["props"]
    for header in ("cache-control", "vary", "content-type", "content-language"):
        assert got.headers.get(header) == missing.headers.get(header), header
    assert "etag" not in got.headers and "etag" not in missing.headers


async def test_conditional_get_needs_visibility(public_locales_client, fx):
    """A guessed validator on a hidden address is a 404, never a 304."""
    for tag in ('W/"abc"', "*"):
        for surface in surfaces(fx, "en"):
            if surface.kind != "page":
                continue
            for hidden in HIDDEN:
                got = await public_locales_client.get(
                    surface.url(fx, "en", hidden), headers=INERTIA | {"If-None-Match": tag}
                )
                assert got.status_code == 404, (surface.name, hidden, tag)


async def test_signed_in_manager_sees_public_only(public_locales_client, fx):
    """The viewer never widens the answer: a signed-in manager gets the anonymous 404 for
    every hidden event (the headers differ only in being private)."""
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    for surface in surfaces(fx, "en"):
        if surface.kind != "page":
            continue
        for hidden in HIDDEN:
            url = surface.url(fx, "en", hidden)
            anon = await public_locales_client.get(url, headers=INERTIA)
            signed = await public_locales_client.get(url, headers=INERTIA | manager)
            assert signed.status_code == anon.status_code == 404, (surface.name, hidden)
            a, b = anon.json(), signed.json()  # an Inertia page's props, or the JSON envelope
            assert b.get("props", b).keys() == a.get("props", a).keys()
            assert signed.headers["cache-control"] == "no-store"


_PUBLIC_CODE = Path(__file__).resolve().parents[3] / "sm_events"
_FORBIDDEN = ("request.state.user", "principal_from", "ResourcePrincipal(")
_ALLOWED = {"_cache.py"}  # reads the user only to choose cache headers


def test_no_viewer_in_public_code():
    """The public surface has no viewer: no handler takes one from the request. Only the
    cache policy looks at who is signed in, to refuse to keep their copy."""
    roots = [_PUBLIC_CODE / "web" / "endpoints" / "public", _PUBLIC_CODE / "feeds"]
    checked = 0
    for root in roots:
        for path in root.rglob("*.py") if root.exists() else ():
            checked += 1
            if path.name in _ALLOWED:
                continue
            source = path.read_text()
            for token in _FORBIDDEN:
                assert token not in source, f"{path.name} uses {token}"
    assert checked >= 8


@pytest.mark.unbound_tenant
async def test_other_tenant_absent_everywhere(public_multi_client):
    """Tenant b's rows, in tenant a's requests: nowhere in a listing, the 404 on their own
    addresses, and a request that resolved no tenant is the 404 too."""
    mine = await seed_public(public_multi_client, tag="-a", tenant="a")
    theirs = await seed_public(public_multi_client, tag="-b", tenant="b")
    as_a = INERTIA | tenant_header("a")
    for locale in LOCALES:
        for surface in surfaces(theirs, locale):
            if surface.kind == "page":
                for hidden in (*HIDDEN, "secret_talk"):
                    got = await public_multi_client.get(
                        surface.url(theirs, locale, hidden), headers=as_a
                    )
                    assert got.status_code == 404, (surface.name, hidden)
                for event in theirs.public_events:
                    slug = theirs.slugs.get(f"{event.id}:{locale}")
                    if slug is None:
                        continue
                    got = await public_multi_client.get(
                        _urls.event_path(slug, locale), headers=as_a
                    )
                    assert got.status_code == 404, (surface.name, slug, "public event of b")
            else:
                # a's own listing, which must hold none of b's; b's calendar's own address is a 404
                got = await public_multi_client.get(surface.url(mine, locale, None), headers=as_a)
                assert got.status_code == 200, surface.name
                for event in theirs.public_events:
                    assert theirs.slugs[f"{event.id}:en"] not in got.text, surface.name
                    assert event.uid not in got.text, surface.name
                assert_absent(got.text, theirs)
        for surface in surfaces(mine, locale):
            nobody = await public_multi_client.get(
                surface.url(mine, locale, "draft")
                if surface.kind == "page"
                else surface.url(mine, locale, None),
                headers=INERTIA,
            )
            assert nobody.status_code == 404, ("no tenant", surface.name)
            assert nobody.headers["cache-control"] == "no-store"
    assert mine.slug(mine.one_off) != theirs.slug(theirs.one_off)


@pytest.mark.xfail(
    strict=True,
    reason="the event page is a stub until Task 13; remove this marker when it lands",
)
async def test_a_public_event_is_not_the_404(public_locales_client, fx):
    """The control the table above lacks: its 404s prove nothing while every route is one.
    Once the page exists this must pass, and the strict xfail forces the marker out."""
    got = await public_locales_client.get(
        _urls.event_path(fx.slug(fx.one_off), "en"), headers=INERTIA
    )
    assert got.status_code == 200
