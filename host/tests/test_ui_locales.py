"""The admin chrome speaks every language the demo host does.

The framework ships the ``ui`` catalogue inside ``simple_module_hosting``
(``ui_locales/``); since 0.0.38 that includes German (upstream #492). This
host's ``host/locales/overrides/de.json`` only keeps the handful of labels it
words differently (see the README there). A framework upgrade that adds a
``ui`` label without German, or drops one an override still names, would
otherwise reach a German console as English, or as a skipped override,
unnoticed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import simple_module_hosting
from simple_module_hosting import Settings
from simple_module_hosting.i18n_manifest import build_i18n_registry

ROOT = Path(__file__).resolve().parents[2]
UI_CATALOG = Path(simple_module_hosting.__file__).resolve().parent / "ui_locales"
GERMAN = ROOT / "host" / "locales" / "overrides" / "de.json"
UI_SRC = ROOT / "node_modules" / "@simple-module-py" / "ui" / "src"
KEY_USE = re.compile(r"keys\.ui\.([A-Za-z0-9_.]+)")
PLACEHOLDER = re.compile(r"\{\{?\s*(\w+)\s*\}?\}")


def _flatten(tree: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        out |= _flatten(value, f"{path}.") if isinstance(value, dict) else {path: value}
    return out


def _english() -> dict[str, str]:
    return _flatten(json.loads((UI_CATALOG / "en.json").read_text()))


def _overrides() -> dict[str, str]:
    return _flatten(json.loads(GERMAN.read_text())["ui"])


def _german() -> dict[str, str]:
    """What a German console shows: the framework's German, then the host's."""
    return _flatten(json.loads((UI_CATALOG / "de.json").read_text())) | _overrides()


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
    known = {re.sub(r"_(zero|one|two|few|many|other)$", "", k) for k in _english()}
    # A section taken whole (``const e = keys.ui.error_page``) is not a leaf.
    sections = {k.rsplit(".", 1)[0] for k in known if "." in k}
    assert sorted(used - known - sections) == []


def test_german_covers_exactly_the_framework_catalog():
    english, german = _english(), _german()
    assert sorted(english.keys() - german.keys()) == [], "untranslated ui keys"
    assert sorted(german.keys() - english.keys()) == [], "keys the framework no longer has"


def test_every_override_changes_the_framework_german():
    """An override equal to the framework's own German is dead weight."""
    shipped = _flatten(json.loads((UI_CATALOG / "de.json").read_text()))
    assert sorted(k for k, v in _overrides().items() if shipped.get(k) == v) == []


def test_german_keeps_every_placeholder():
    english, german = _english(), _german()
    drift = {
        key: text
        for key, text in german.items()
        if set(PLACEHOLDER.findall(text)) != set(PLACEHOLDER.findall(english.get(key, "")))
    }
    assert drift == {}


def test_the_host_serves_the_ui_namespace_in_german():
    settings = Settings(i18n_supported_locales=["en", "de"])
    registry, _ = build_i18n_registry(settings, [], ROOT)
    assert registry.messages("en").get("ui.sidebar.open") == "Open sidebar"
    assert registry.messages("de").get("ui.sidebar.open") == "Seitenleiste öffnen"
    assert registry.messages("de").get("ui.nav_groups.content") == "Inhalte"
    assert registry.unknown_override_keys == {}
