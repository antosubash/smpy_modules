"""The vendored ``ui`` catalog covers what the installed ``ui`` package renders.

``packages/ui/locales/`` is copied from the framework (see its README) because
the published package does not ship it. A framework upgrade that adds a label
would otherwise reach the admin chrome as a raw ``ui.…`` key, unnoticed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from simple_module_hosting import Settings
from simple_module_hosting.i18n_manifest import build_i18n_registry

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "packages" / "ui" / "locales"
UI_SRC = ROOT / "node_modules" / "@simple-module-py" / "ui" / "src"
KEY_USE = re.compile(r"keys\.ui\.([A-Za-z0-9_.]+)")


def _flatten(tree: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for key, value in tree.items():
        path = f"{prefix}{key}"
        out |= _flatten(value, f"{path}.") if isinstance(value, dict) else {path}
    return out


def _catalog(locale: str) -> set[str]:
    return _flatten(json.loads((CATALOG / f"{locale}.json").read_text()))


def test_every_ui_key_the_package_uses_is_in_the_catalog():
    if not UI_SRC.is_dir():
        pytest.skip("node_modules not installed")
    used = {
        match
        for path in UI_SRC.rglob("*.tsx")
        if not path.name.endswith(".test.tsx")
        for match in KEY_USE.findall(path.read_text())
    }
    assert used, "the ui package uses no keys.ui.* — has its i18n moved?"
    # A plural key is used by its stem and stored with ``_one``/``_other``.
    known = {re.sub(r"_(zero|one|two|few|many|other)$", "", k) for k in _catalog("en")}
    assert sorted(used - known) == []


def test_every_locale_has_the_same_keys():
    assert _catalog("es") == _catalog("en")


def test_the_host_serves_the_ui_namespace():
    registry, _ = build_i18n_registry(Settings(), [], ROOT)
    assert registry.messages("en").get("ui.sidebar.open") == "Open sidebar"
