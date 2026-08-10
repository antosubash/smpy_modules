"""Invariants of the stored seed content itself.

The seed was extracted from IIASA.GeoWiki, which served these pages at
``/gca/<slug>`` and typed a heading level as a bare ``"3"``. Neither survives
the move: this app routes pages at ``/p/<slug>``, and the Heading block's
``level`` is the tag name it renders, so ``"3"`` produced a literal ``<3>``.
Both classes of breakage were invisible until a page was opened, so they are
pinned here rather than left to review.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest

CONTENT_DIR = files("canopy_atlas") / "seed" / "content"
STATIC_DIR = files("canopy_atlas") / "static"

MANIFEST = json.loads((CONTENT_DIR / "_manifest.json").read_text())
SLUGS = [entry["slug"] for entry in MANIFEST]
ARTICLE_SLUGS = {
    article["slug"] for article in json.loads((CONTENT_DIR / "_articles.json").read_text())
}

# The only ``/gca/...`` strings allowed in content are asset paths, which
# ``rewrite_asset_paths`` resolves at seed time. Anything else is a page route
# that never existed in this app.
ASSET_PREFIXES = ("/gca/images/", "/gca/partners/", "/gca/logo")

HEADING_LEVELS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _page(slug: str) -> dict[str, Any]:
    return json.loads((CONTENT_DIR / f"{slug}.json").read_text())


def _blocks(node: Any) -> list[dict[str, Any]]:
    """Every Puck block in a tree, including ones nested inside props."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "type" in node and isinstance(node.get("props"), dict):
            found.append(node)
        for value in node.values():
            found += _blocks(value)
    elif isinstance(node, list):
        for value in node:
            found += _blocks(value)
    return found


def _strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for value in node.values() for s in _strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in _strings(value)]
    return [node] if isinstance(node, str) else []


ALL_SOURCES = [*SLUGS, "_layout", "_articles"]


@pytest.mark.parametrize("name", ALL_SOURCES)
def test_no_page_is_linked_at_a_geowiki_route(name: str) -> None:
    """``/gca/<slug>`` is a GeoWiki route; this app publishes at ``/p/<slug>``."""
    stale = [
        s
        for s in _strings(json.loads((CONTENT_DIR / f"{name}.json").read_text()))
        if s.startswith("/gca/") and not s.startswith(ASSET_PREFIXES)
    ]
    assert stale == [], f"{name}: {stale} would 404 — link pages at /p/<slug>"


@pytest.mark.parametrize("slug", SLUGS)
def test_internal_links_resolve_to_a_seeded_page(slug: str) -> None:
    known = {f"/p/{s}" for s in (*SLUGS, *ARTICLE_SLUGS)}
    broken = [s for s in _strings(_page(slug)) if s.startswith("/p/") and s not in known]
    assert broken == [], f"{slug} links to unseeded page(s): {broken}"


@pytest.mark.parametrize("slug", SLUGS)
def test_heading_levels_are_tag_names(slug: str) -> None:
    """``level`` is rendered as the tag, so a bare "3" emits ``<3>``."""
    bad = [
        block["props"].get("level")
        for block in _blocks(_page(slug))
        if block["type"] == "Heading" and block["props"].get("level") not in HEADING_LEVELS
    ]
    assert bad == [], f"{slug} has Heading level(s) {bad}; expected one of {sorted(HEADING_LEVELS)}"


@pytest.mark.parametrize("name", ALL_SOURCES)
def test_every_asset_path_exists_on_disk(name: str) -> None:
    """A typo'd asset only shows up as a broken image on a rendered page."""
    missing = [
        s
        for s in _strings(json.loads((CONTENT_DIR / f"{name}.json").read_text()))
        if s.startswith(ASSET_PREFIXES) and not (STATIC_DIR / s.lstrip("/")).is_file()
    ]
    assert missing == [], f"{name} references missing asset(s): {missing}"


def test_manifest_and_content_files_agree() -> None:
    on_disk = {
        path.name.removesuffix(".json")
        for path in CONTENT_DIR.iterdir()
        if path.name.endswith(".json") and not path.name.startswith("_")
    }
    assert on_disk == set(SLUGS)
