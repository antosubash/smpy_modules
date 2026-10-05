"""Every sidebar icon a module names must exist in the framework's NavIcon map.

``NavIcon`` renders an empty box for a name it does not know, so a typo or a
lucide name the map never imported ships as a blank space in the sidebar with
no error anywhere. News did exactly that with ``newspaper``/``tags``/``trash-2``.

Skipped when the frontend is not installed (``node_modules`` absent).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NAV_ICON = REPO / "node_modules" / "@simple-module-py" / "ui" / "src" / "components" / "NavIcon.tsx"

# `MENU_ICON: Final = "x"`, `_ICON_PAGES = "x"`, `icon="x"`.
_NAMED = re.compile(r"""\b\w*ICON\w*\s*(?::\s*Final\s*)?=\s*["']([a-z0-9-]+)["']""")
_INLINE = re.compile(r"""\bicon\s*=\s*["']([a-z0-9-]+)["']""")


def _known_icons() -> set[str]:
    source = NAV_ICON.read_text(encoding="utf-8")
    body = source.split("const ICON_MAP", 1)[1].split("} as const", 1)[0]
    return set(re.findall(r"""^\s*'?([a-z0-9-]+)'?\s*:""", body, re.MULTILINE))


def _module_icons() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in (REPO / "modules").glob("*/*/**/*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        names = set(_NAMED.findall(text)) | set(_INLINE.findall(text))
        if names:
            found[str(path.relative_to(REPO))] = names
    return found


@pytest.mark.skipif(not NAV_ICON.exists(), reason="frontend not installed")
def test_every_module_icon_is_one_navicon_renders() -> None:
    known = _known_icons()
    assert len(known) > 20, "could not parse NavIcon's ICON_MAP"
    assert "search" in known
    module_icons = _module_icons()
    assert module_icons, "found no icon names in any module; the patterns are stale"
    unknown = {
        path: sorted(names - known)
        for path, names in module_icons.items()
        if names - known
    }
    assert unknown == {}, f"icons NavIcon cannot render (blank in the sidebar): {unknown}"
