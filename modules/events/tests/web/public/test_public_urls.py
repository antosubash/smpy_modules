"""Path builders and the origin."""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace

import pytest
from sm_events.core import locales
from sm_events.core.tenancy import TenancyMode
from sm_events.web.endpoints.public import _urls


@pytest.fixture(autouse=True)
def _restore():
    yield
    _urls.use("/events")
    locales.reset()


def test_paths():
    locales.use("en", "de")
    assert _urls.index_path("en") == "/events/"
    assert _urls.index_path("de") == "/de/events/"
    assert _urls.event_path("x", "en") == "/events/x"
    assert _urls.event_path("x", "de", date(2026, 7, 6)) == "/de/events/x?date=2026-07-06"
    assert _urls.event_ics_path("x", "de") == "/de/events/x.ics"
    assert _urls.calendar_path("team", "en") == "/events/c/team"
    assert _urls.calendar_ics_path(None, "de") == "/de/events/calendar.ics"
    assert _urls.calendar_ics_path("team", "en") == "/events/c/team.ics"
    assert _urls.sitemap_path() == "/events/sitemap.xml"
    assert _urls.api_path() == "/events/api/occurrences"


def test_custom_prefix():
    _urls.use("/whats-on")
    locales.use("en", "de")
    assert _urls.prefix() == "/whats-on"
    assert _urls.event_path("x", "en") == "/whats-on/x"
    assert _urls.event_path("x", "de", date(2026, 7, 6)) == "/de/whats-on/x?date=2026-07-06"
    assert _urls.calendar_ics_path("team", "en") == "/whats-on/c/team.ics"
    assert _urls.sitemap_path() == "/whats-on/sitemap.xml"


def test_the_default_language_follows_the_first_locale():
    locales.use("de", "en")
    assert _urls.event_path("x", "de") == "/events/x"
    assert _urls.event_path("x", "en") == "/en/events/x"


def test_a_slug_is_one_path_segment():
    assert _urls.event_path("a/b?c", "en") == "/events/a%2Fb%3Fc"


def _app(origin: str | None, mode: TenancyMode, environment: str = "production"):
    host = SimpleNamespace(environment=environment)
    if origin is not None:
        host.public_base_url = origin
    return SimpleNamespace(
        state=SimpleNamespace(
            sm=SimpleNamespace(settings=host), sm_events=SimpleNamespace(tenancy=mode)
        )
    )


def _request(app, netloc: str = "visitor.test"):
    url = SimpleNamespace(scheme="https", netloc=netloc)
    return SimpleNamespace(app=app, url=url)


def test_origin():
    single = _app("https://www.example.org/", TenancyMode.SINGLE)
    assert _urls.configured_origin(single) == "https://www.example.org"
    assert _urls.public_base_url(_request(single)) == "https://www.example.org"
    assert _urls.absolute(_request(single), "/events/x") == "https://www.example.org/events/x"
    assert not _urls.guessed(single)
    multi = _app("https://www.example.org", TenancyMode.MULTI)
    assert _urls.configured_origin(multi) == ""
    assert _urls.public_base_url(_request(multi, "acme.example.org")) == "https://acme.example.org"
    assert _urls.guessed(multi)
    blank = _app("", TenancyMode.SINGLE)
    assert _urls.public_base_url(_request(blank)) == "https://visitor.test"


@pytest.mark.parametrize(
    ("app", "mode", "warns"),
    [
        (_app("", TenancyMode.SINGLE), TenancyMode.SINGLE, True),
        (_app(None, TenancyMode.SINGLE), TenancyMode.SINGLE, True),
        (_app("https://e.org", TenancyMode.SINGLE), TenancyMode.SINGLE, False),
        (_app("", TenancyMode.MULTI), TenancyMode.MULTI, False),
        (_app("", TenancyMode.SINGLE, "development"), TenancyMode.SINGLE, False),
        (_app("", TenancyMode.SINGLE, "testing"), TenancyMode.SINGLE, False),
    ],
)
def test_warn_if_unset(app, mode, warns, caplog):
    with caplog.at_level(logging.WARNING, logger="sm_events.public"):
        assert _urls.warn_if_unset(app, mode) is warns
    assert bool(caplog.records) is warns
