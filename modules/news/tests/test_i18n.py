"""The console catalogue, and the wiring that gets it to a browser.

The frontend derives its key tree from ``news/locales/en.json`` at compile
time, so ``tsc`` catches a key that does not exist. What it cannot see is the
Python half: if ``locale_dirs`` stops pointing at the directory, or the wheel
stops shipping the JSON, nothing fails to build — every label in the console
just renders as its own dotted key.
"""

from __future__ import annotations

import json
from pathlib import Path

from news import constants
from news.module import NewsModule
from simple_module_core.i18n import PLURAL_CATEGORIES, I18nRegistry, flatten_messages

LOCALE_DIR = Path(__file__).resolve().parent.parent / "news" / "locales"


def test_module_registers_its_locale_directory() -> None:
    dirs = NewsModule().locale_dirs()
    assert set(dirs) == {constants.LOCALE_NAMESPACE}
    registered = Path(str(dirs[constants.LOCALE_NAMESPACE]))
    assert registered.is_dir()
    assert (registered / "en.json").is_file()


def test_namespace_matches_the_frontend_prefix() -> None:
    """``utils/i18n.ts`` hardcodes the same prefix; a mismatch is silent."""
    source = (LOCALE_DIR.parent / "utils" / "i18n.ts").read_text(encoding="utf-8")
    assert f"const NAMESPACE = '{constants.LOCALE_NAMESPACE}';" in source


def test_catalogue_flattens_to_string_leaves() -> None:
    raw = json.loads((LOCALE_DIR / "en.json").read_text(encoding="utf-8"))
    flat = flatten_messages(raw)
    assert flat, "the catalogue is empty"
    assert all(isinstance(value, str) for value in flat.values())


def test_registry_loads_it_under_the_namespace() -> None:
    """What the host does at boot, and what the ``i18n`` shared prop carries."""
    registry = I18nRegistry(default_locale="en", supported_locales=["en"])
    for namespace, path in NewsModule().locale_dirs().items():
        registry.add_source(namespace, Path(str(path)))
    registry.load()
    messages = registry.messages("en")
    assert messages[f"{constants.LOCALE_NAMESPACE}.list.title"] == "News"
    assert all(key.startswith(f"{constants.LOCALE_NAMESPACE}.") for key in messages)


def test_plural_entries_carry_both_english_forms() -> None:
    """A stem missing a form renders as the raw key for the counts it misses."""
    flat = flatten_messages(json.loads((LOCALE_DIR / "en.json").read_text(encoding="utf-8")))
    stems = set()
    for key in flat:
        for category in PLURAL_CATEGORIES:
            if key.endswith(f"_{category}"):
                stems.add(key[: -len(category) - 1])
    assert stems, "no plural entries — the check would pass vacuously"
    for stem in stems:
        assert f"{stem}_one" in flat
        assert f"{stem}_other" in flat
