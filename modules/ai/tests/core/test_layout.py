"""Consumer discovery remains stable while internal code follows the module layout."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from sm_ai import contracts
from sm_ai.module import AiModule

# Until 0.0.17 the old directories hold nothing but moved-path stubs (#319).
_STUB = ("/** @deprecated Moved to ", "/* @deprecated Moved to ")


def _only_stubs(path: Path) -> bool:
    files = [f for f in path.rglob("*") if f.is_file() and "__pycache__" not in f.parts]
    return bool(files) and all(f.read_text(encoding="utf-8").startswith(_STUB) for f in files)


def test_package_root_contains_only_discovery_paths():
    root = Path(contracts.__file__).parents[1]
    assert {p.name for p in root.glob("*.py")} == {"__init__.py", "module.py"}
    dirs = [p for p in root.iterdir() if p.is_dir() and p.name != "__pycache__"]
    assert {p.name for p in dirs if not _only_stubs(p)} == {
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
