"""The editor's bundled font is allowed from the Vite origin in dev only (#188)."""

from __future__ import annotations

from types import SimpleNamespace

from pagebuilder.dev_csp import vite_font_source
from pagebuilder.module import PagebuilderModule
from simple_module_core.csp import CspSourceRegistry


def _app(environment: str | None, dev_url: str = "http://localhost:5050") -> SimpleNamespace:
    config = (
        None if environment is None else SimpleNamespace(environment=environment, dev_url=dev_url)
    )
    return SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(inertia_config=config)))


def test_development_allows_fonts_from_the_vite_origin() -> None:
    assert list(vite_font_source(_app("development", "http://localhost:5101/"))) == [
        ("font-src", "http://localhost:5101")
    ]


def test_production_policy_is_unchanged() -> None:
    assert list(vite_font_source(_app("production"))) == []


def test_without_inertia_config_nothing_is_added() -> None:
    assert list(vite_font_source(_app(None))) == []
    assert list(vite_font_source(SimpleNamespace(state=SimpleNamespace()))) == []


def test_the_module_registers_the_provider() -> None:
    registry = CspSourceRegistry()
    PagebuilderModule().register_csp_sources(registry)

    assert registry.providers == (vite_font_source,)
    # A provider, not a static source: production's policy string is untouched.
    assert not registry
