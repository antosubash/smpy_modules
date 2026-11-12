"""A guessed public origin (#355): ``Vary: Host`` and a startup warning.

With ``public_base_url`` blank, canonical, ``og:url``, ``hreflang`` and the
sitemap are built from the request's ``Host``. Every response whose body names
that origin then varies on ``Host``, so a shared cache cannot hand one host's
links to another; with the setting, nothing changes.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.core.tenancy import TenancyMode
from pagebuilder.web import public_origin
from pagebuilder.web.public_origin import vary_on_host, warn_if_unset
from starlette.responses import Response

_ANON = {"X-Test-Anonymous": "1"}


def _vary(response) -> set[str]:
    return {v.strip().lower() for v in response.headers.get("vary", "").split(",") if v.strip()}


async def _publish(client: AsyncClient, slug: str = "hello") -> None:
    created = await client.post(
        "/api/pagebuilder/pages",
        json={"title": "Hello", "slug": slug, "draft_data": {"content": []}},
    )
    assert created.status_code == 201, created.text
    published = await client.post(f"/api/pagebuilder/pages/{created.json()['id']}/publish")
    assert published.status_code == 200, published.text


def _settings(client: AsyncClient) -> PagebuilderSettings:
    return client._transport.app.state.pagebuilder.settings  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/p/hello", "/sitemap.xml", "/robots.txt"])
async def test_a_guessed_origin_varies_on_host(authed_client: AsyncClient, path: str) -> None:
    await _publish(authed_client)
    _settings(authed_client).public_base_url = None
    response = await authed_client.get(path, headers=_ANON)
    assert response.status_code == 200, response.text
    assert "host" in _vary(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/p/hello", "/sitemap.xml", "/robots.txt"])
async def test_a_configured_origin_does_not(authed_client: AsyncClient, path: str) -> None:
    await _publish(authed_client)
    _settings(authed_client).public_base_url = "https://example.com"
    response = await authed_client.get(path, headers=_ANON)
    assert response.status_code == 200, response.text
    assert "host" not in _vary(response)
    if path != "/p/hello":
        assert "https://example.com/" in response.text


@pytest.mark.asyncio
async def test_a_304_varies_on_host_too(authed_client: AsyncClient) -> None:
    await _publish(authed_client)
    first = await authed_client.get("/p/hello", headers=_ANON)
    again = await authed_client.get(
        "/p/hello", headers={**_ANON, "If-None-Match": first.headers["ETag"]}
    )
    assert again.status_code == 304
    assert "host" in _vary(again)


@pytest.mark.asyncio
async def test_a_custom_robots_body_names_no_origin(authed_client: AsyncClient) -> None:
    _settings(authed_client).robots_body = "User-agent: *\nDisallow: /\n"
    response = await authed_client.get("/robots.txt")
    assert "host" not in _vary(response)


@pytest.mark.asyncio
async def test_the_hosts_public_base_url_stands_in(authed_client: AsyncClient) -> None:
    """A blank module setting falls back to the host's own ``public_base_url``
    on a single-tenant host, before the request's Host."""
    await _publish(authed_client)
    _settings(authed_client).public_base_url = None
    # This harness builds no host settings; a real host has them here.
    sm = authed_client._transport.app.state.sm  # type: ignore[attr-defined]
    sm.settings = SimpleNamespace(environment="production", public_base_url="https://site.example")
    sitemap = await authed_client.get("/sitemap.xml", headers=_ANON)
    assert "https://site.example/p/hello" in sitemap.text
    assert "host" not in _vary(sitemap)
    page = await authed_client.get("/p/hello", headers=_ANON)
    assert "host" not in _vary(page)


def test_vary_on_host_appends_once(monkeypatch) -> None:
    monkeypatch.setattr(public_origin, "mode_of", lambda app: TenancyMode.SINGLE)
    settings = PagebuilderSettings()
    request = SimpleNamespace(app=_app("production"))
    response = Response(headers={"Vary": "Cookie, host"})
    assert vary_on_host(response, request, settings).headers["Vary"] == "Cookie, host"  # type: ignore[arg-type]
    response = Response(headers={"Vary": "Cookie"})
    assert vary_on_host(response, request, settings).headers["Vary"] == "Cookie, Host"  # type: ignore[arg-type]


def _app(environment: str | None, host_base: str = "") -> SimpleNamespace:
    host = SimpleNamespace(
        settings=SimpleNamespace(environment=environment, public_base_url=host_base)
    )
    return SimpleNamespace(state=SimpleNamespace(sm=host))


@pytest.mark.parametrize(
    ("environment", "mode", "base", "warns"),
    [
        ("production", TenancyMode.SINGLE, None, True),
        (None, TenancyMode.SINGLE, "", True),
        ("staging", TenancyMode.SINGLE, None, True),
        ("development", TenancyMode.SINGLE, None, False),
        ("testing", TenancyMode.SINGLE, None, False),
        ("production", TenancyMode.MULTI, None, False),
        ("production", TenancyMode.SINGLE, "https://example.com", False),
        ("production", TenancyMode.SINGLE, "host", False),
    ],
)
def test_the_startup_warning(monkeypatch, caplog, environment, mode, base, warns) -> None:
    monkeypatch.setattr(public_origin, "mode_of", lambda app: mode)
    host_base = "https://site.example" if base == "host" else ""
    settings = PagebuilderSettings(public_base_url=None if base == "host" else base)
    with caplog.at_level(logging.WARNING, logger=public_origin.__name__):
        assert warn_if_unset(_app(environment, host_base), settings) is warns
    assert any("public_base_url" in r.message for r in caplog.records) is warns
