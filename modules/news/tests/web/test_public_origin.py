"""The startup warning for a guessed public origin (#355).

The ``Vary: Host`` half is in ``tests/core/test_tenancy_public.py``, next to
the rest of the public responses' ``Vary``.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from news.core.settings import NewsSettings
from news.core.tenancy import TenancyMode
from news.web.endpoints.public._urls import public_base_url, warn_if_unset


def _app(environment: str | None) -> SimpleNamespace:
    host = SimpleNamespace(settings=SimpleNamespace(environment=environment))
    return SimpleNamespace(state=SimpleNamespace(sm=host))


@pytest.mark.parametrize(
    ("environment", "mode", "base", "warns"),
    [
        ("production", TenancyMode.SINGLE, "", True),
        (None, TenancyMode.SINGLE, "  ", True),
        ("staging", TenancyMode.SINGLE, "", True),
        ("development", TenancyMode.SINGLE, "", False),
        ("testing", TenancyMode.SINGLE, "", False),
        ("production", TenancyMode.MULTI, "", False),
        ("production", TenancyMode.SINGLE, "https://news.example", False),
    ],
)
def test_the_startup_warning(caplog, environment, mode, base, warns) -> None:
    settings = NewsSettings(public_base_url=base)
    with caplog.at_level(logging.WARNING, logger="simple_module.news"):
        assert warn_if_unset(_app(environment), settings, mode) is warns
    assert any("public_base_url is not set" in r.message for r in caplog.records) is warns


def test_the_setting_wins_over_the_request() -> None:
    request = SimpleNamespace(url=SimpleNamespace(scheme="http", netloc="evil.example"))
    settings = NewsSettings(public_base_url="https://news.example/")
    assert public_base_url(request, settings) == "https://news.example"  # type: ignore[arg-type]
    settings = NewsSettings(public_base_url="")
    assert public_base_url(request, settings) == "http://evil.example"  # type: ignore[arg-type]
