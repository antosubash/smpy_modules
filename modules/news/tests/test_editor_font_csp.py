"""The article editor's bundled font is allowed from the Vite origin in dev only (#188).

News registers the provider itself, so a host running news without pagebuilder
still loads Inter under ``vite dev``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from news.dev_csp import vite_font_source, vite_origin
from news.module import NewsModule
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


@pytest.mark.parametrize(
    ("raw", "origin"),
    [
        ("http://localhost:5093", "http://localhost:5093"),
        ("https://Dev.Example.com/", "https://dev.example.com"),
        ("http://127.0.0.1:5173", "http://127.0.0.1:5173"),
        ("http://[::1]:5173", "http://[::1]:5173"),
    ],
)
def test_a_concrete_origin_is_kept(raw: str, origin: str) -> None:
    assert vite_origin(raw) == origin


@pytest.mark.parametrize(
    "raw",
    [
        "",
        None,
        "https:",
        "https://",
        "http:",
        "*",
        "https://*.example.com",
        "http://*:5173",
        "ftp://localhost:21",
        "ws://localhost:5173",
        "data:",
        "localhost:5173",
        "//localhost:5173",
        "http://user:pass@localhost:5173",
        "http://user@localhost:5173",
        "http://localhost:5173/assets/",
        "http://localhost:5173?x=1",
        "http://localhost:5173#frag",
        "http://localhost:notaport",
        "http://localhost:99999",
        "http://local_host:5173",
        "http://localhost:5173 https://evil.example",
        "http://localhost;script-src *",
        "http://-bad.example",
    ],
)
def test_anything_broader_than_one_origin_is_refused(raw: str | None) -> None:
    assert vite_origin(raw) is None
    assert list(vite_font_source(_app("development", raw or ""))) == []


def test_production_policy_is_unchanged() -> None:
    assert list(vite_font_source(_app("production"))) == []


def test_without_inertia_config_nothing_is_added() -> None:
    assert list(vite_font_source(_app(None))) == []
    assert list(vite_font_source(SimpleNamespace(state=SimpleNamespace()))) == []


def test_the_module_registers_the_provider() -> None:
    registry = CspSourceRegistry()
    NewsModule().register_csp_sources(registry)

    assert registry.providers == (vite_font_source,)
    # A provider, not a static source: production's policy string is untouched.
    assert not registry
