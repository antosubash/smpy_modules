"""The ``map_style_url`` setting: its rule, and the CSP origin it opens."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from simple_module_core.csp import CspSourceRegistry
from simple_module_hosting._csp_dynamic import DynamicCsp
from sm_images.map.style import DEFAULT_STYLE_URL, csp_sources, style_origin
from sm_images.module import ImagesModule
from sm_images.settings import ImagesSettings

BASE = "default-src 'self'; img-src 'self' data: blob:; connect-src 'self'"


def _app(url: str) -> SimpleNamespace:
    settings = ImagesSettings(map_style_url=url)
    return SimpleNamespace(state=SimpleNamespace(sm_images=SimpleNamespace(settings=settings)))


def test_default_is_openfreemap_positron():
    assert ImagesSettings().map_style_url == DEFAULT_STYLE_URL
    assert DEFAULT_STYLE_URL == "https://tiles.openfreemap.org/styles/positron"


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("", ""),
        ("   ", ""),
        (" https://tiles.example.org/style.json ", "https://tiles.example.org/style.json"),
        ("https://tiles.example.org:8443/s?key=1", "https://tiles.example.org:8443/s?key=1"),
    ],
)
def test_empty_or_https_is_accepted(given, kept):
    assert ImagesSettings(map_style_url=given).map_style_url == kept


@pytest.mark.parametrize(
    "bad",
    [
        "http://tiles.example.org/style.json",
        "tiles.example.org/style.json",
        "/static/style.json",
        "https://",
        "https://user:pw@tiles.example.org/s",
        "https://tiles.example.org/a b",
        "javascript:alert(1)",
        "https://tiles.example.org; script-src *",
    ],
)
def test_anything_else_is_refused(bad):
    with pytest.raises(ValidationError):
        ImagesSettings(map_style_url=bad)


def test_origin_keeps_only_scheme_host_and_port():
    assert style_origin("https://Tiles.Example.org:8443/styles/x?y=1") == (
        "https://tiles.example.org:8443"
    )
    assert style_origin("") is None


def test_provider_allows_the_style_origin_for_fetches_and_images():
    pairs = list(csp_sources(_app(DEFAULT_STYLE_URL)))
    assert pairs == [
        ("connect-src", "https://tiles.openfreemap.org"),
        ("img-src", "https://tiles.openfreemap.org"),
    ]


def test_provider_adds_nothing_for_a_flat_map_or_an_unbooted_app():
    assert list(csp_sources(_app(""))) == []
    assert list(csp_sources(SimpleNamespace(state=SimpleNamespace()))) == []


def test_module_registers_the_provider_and_the_policy_follows_the_setting():
    registry = CspSourceRegistry()
    ImagesModule().register_csp_sources(registry)
    csp = DynamicCsp(BASE, registry)
    policy = csp.policy_for(_app(DEFAULT_STYLE_URL))
    assert "connect-src 'self' https://tiles.openfreemap.org" in policy
    assert "img-src 'self' data: blob: https://tiles.openfreemap.org" in policy
    # An edit applies on the next response; empty leaves the strict policy.
    assert "https://maps.example.org" in csp.policy_for(_app("https://maps.example.org/s"))
    assert csp.policy_for(_app("")) == BASE
