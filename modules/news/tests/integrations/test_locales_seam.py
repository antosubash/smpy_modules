"""news' locale seam asks ``pagebuilder.contracts.site``, not pagebuilder's internals (#336)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("pagebuilder.contracts.site")

from news.integrations import locales as seam
from pagebuilder.contracts import site
from pagebuilder.core.settings import PagebuilderSettings


def _app(settings: object | None) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(pagebuilder=SimpleNamespace(settings=settings)))


def test_hydrated_locales_reads_the_app_through_the_contract():
    settings = PagebuilderSettings(content_locales=("en", "fr"), default_content_locale="en")
    assert seam.hydrated_locales(_app(settings)) == (("en", "fr"), "en")


def test_hydrated_locales_without_pagebuilder_mounted_is_none():
    assert seam.hydrated_locales(SimpleNamespace(state=SimpleNamespace())) is None
    assert seam.hydrated_locales(_app(None)) is None


def test_the_process_wide_reads_go_through_the_contract(monkeypatch):
    monkeypatch.setattr(site, "supported", lambda: ("xx", "yy"))
    monkeypatch.setattr(site, "default", lambda: "xx")
    monkeypatch.setattr(site, "is_default", lambda locale: locale == "xx")
    monkeypatch.setattr(site, "resolve", lambda value: f"r:{value}")
    monkeypatch.setattr(site, "path_prefix", lambda locale: f"/{locale}")
    assert seam.content_locales() == ("xx", "yy")
    assert seam.default_locale() == "xx"
    assert seam.is_default_locale("xx") is True
    assert seam.resolve_locale("De") == "r:De"
    assert seam.locale_path_prefix("yy") == "/yy"
