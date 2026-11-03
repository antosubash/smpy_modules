"""Consumer discovery remains stable while internal code follows the module layout."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from sm_ai import contracts
from sm_ai.module import AiModule


def test_package_root_contains_only_discovery_paths():
    root = Path(contracts.__file__).parents[1]
    assert {p.name for p in root.glob("*.py")} == {"__init__.py", "module.py"}
    assert {p.name for p in root.iterdir() if p.is_dir() and p.name != "__pycache__"} == {
        "connections",
        "contracts",
        "core",
        "locales",
        "metering",
        "pages",
        "ui",
        "web",
    }


def test_host_discovers_the_module_and_locales():
    entry = next(
        ep for ep in importlib.metadata.entry_points(group="simple_module") if ep.name == "ai"
    )
    assert entry.load() is AiModule
    locales = AiModule().locale_dirs()["ai"]
    assert (locales / "en.json").is_file()
    assert (locales / "de.json").is_file()
    assert (locales.parent / "pages" / "Settings.tsx").is_file()
