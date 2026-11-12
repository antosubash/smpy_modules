"""The startup warning for a guessed public origin (#355).

The ``Vary: Host`` half is in ``tests/core/test_tenancy_public.py``, next to
the rest of the public responses' ``Vary``.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from news.core import tenancy
from news.core.settings import NewsSettings
from news.core.tenancy import TenancyMode
from news.web.endpoints.public._urls import public_base_url, warn_if_unset


def _app(environment: str | None, host_base: str = "") -> SimpleNamespace:
    host = SimpleNamespace(
        settings=SimpleNamespace(environment=environment, public_base_url=host_base)
    )
    return SimpleNamespace(state=SimpleNamespace(sm=host))


@pytest.fixture
def mode(monkeypatch):
    """Which tenancy mode ``configured_origin`` sees (it reads ``mode_of``)."""
    current = {"mode": TenancyMode.SINGLE}
    monkeypatch.setattr(tenancy, "mode_of", lambda app: current["mode"])
    return current


@pytest.mark.parametrize(
    ("environment", "kind", "base", "warns"),
    [
        ("production", TenancyMode.SINGLE, "", True),
        (None, TenancyMode.SINGLE, "  ", True),
        ("staging", TenancyMode.SINGLE, "", True),
        ("development", TenancyMode.SINGLE, "", False),
        ("testing", TenancyMode.SINGLE, "", False),
        ("production", TenancyMode.MULTI, "", False),
        ("production", TenancyMode.SINGLE, "https://news.example", False),
        ("production", TenancyMode.SINGLE, "host", False),
    ],
)
def test_the_startup_warning(caplog, mode, environment, kind, base, warns) -> None:
    mode["mode"] = kind
    host_base = "https://site.example" if base == "host" else ""
    settings = NewsSettings(public_base_url="" if base == "host" else base)
    with caplog.at_level(logging.WARNING, logger="simple_module.news"):
        assert warn_if_unset(_app(environment, host_base), settings, kind) is warns
    said = [r.message for r in caplog.records if "public_base_url" in r.message]
    assert bool(said) is warns
    for message in said:
        assert "news' public_base_url nor the host's public_base_url" in message


def _request(host_base: str = "") -> SimpleNamespace:
    url = SimpleNamespace(scheme="http", netloc="evil.example")
    return SimpleNamespace(url=url, app=_app("production", host_base))


def test_the_setting_wins_over_the_request(mode) -> None:
    settings = NewsSettings(public_base_url="https://news.example/")
    assert public_base_url(_request(), settings) == "https://news.example"  # type: ignore[arg-type]
    settings = NewsSettings(public_base_url="")
    assert public_base_url(_request(), settings) == "http://evil.example"  # type: ignore[arg-type]


def test_the_hosts_public_base_url_comes_next_on_a_single_tenant_host(mode) -> None:
    settings = NewsSettings(public_base_url="")
    request = _request("https://site.example/")
    assert public_base_url(request, settings) == "https://site.example"  # type: ignore[arg-type]
    mode["mode"] = TenancyMode.MULTI
    assert public_base_url(request, settings) == "http://evil.example"  # type: ignore[arg-type]
