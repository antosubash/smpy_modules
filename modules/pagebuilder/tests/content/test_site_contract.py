"""``pagebuilder.contracts.site``: what other modules ask instead of ``app.state`` (#336)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pagebuilder import contracts
from pagebuilder.contracts import site
from pagebuilder.core import locales
from pagebuilder.core.settings import PagebuilderSettings


def _app(settings: object | None = None, *, mounted: bool = True) -> SimpleNamespace:
    state = SimpleNamespace()
    if mounted:
        state.pagebuilder = SimpleNamespace(settings=settings)
    return SimpleNamespace(state=state)


def test_content_locales_reads_the_hydrated_settings_on_the_app():
    settings = PagebuilderSettings(content_locales=("de", "en"), default_content_locale="de")
    found = site.content_locales(_app(settings))
    assert found == site.ContentLocales(("de", "en"), "de")
    assert found is not None
    assert found.locales == ("de", "en")
    assert found.default == "de"


def test_content_locales_without_pagebuilder_is_none():
    assert site.content_locales(_app(mounted=False)) is None
    assert site.content_locales(_app(None)) is None
    assert site.content_locales(object()) is None


@pytest.mark.parametrize(
    ("csp", "expected"),
    [
        ("script-src 'self'", "script-src 'self'"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_public_csp(csp, expected):
    assert site.public_csp(_app(SimpleNamespace(public_csp=csp))) == expected


def test_public_csp_without_pagebuilder_is_none():
    assert site.public_csp(_app(mounted=False)) is None
    assert site.public_csp(SimpleNamespace()) is None


def test_public_csp_reads_the_real_settings_field():
    settings = PagebuilderSettings(public_csp="default-src 'self'")
    assert site.public_csp(_app(settings)) == "default-src 'self'"


def test_the_process_wide_readers_are_pagebuilders_own():
    assert site.supported is locales.supported
    assert site.default is locales.default
    assert site.is_default is locales.is_default
    assert site.resolve is locales.resolve
    assert site.path_prefix is locales.path_prefix


def test_site_is_exported_from_contracts():
    assert contracts.site is site
    assert "site" in contracts.__all__
