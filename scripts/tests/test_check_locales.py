"""The catalogue check catches drift between en.json and its translations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_locales


def _write(locales: Path, name: str, data: dict) -> None:
    locales.mkdir(parents=True, exist_ok=True)
    (locales / name).write_text(json.dumps(data), encoding="utf-8")


def _locales(tmp_path: Path) -> Path:
    return tmp_path / "modules" / "demo" / "demo" / "locales"


def test_matching_catalogue_passes(tmp_path):
    loc = _locales(tmp_path)
    _write(loc, "en.json", {"a": {"b": "Hi {name}"}})
    _write(loc, "de.json", {"a": {"b": "Hallo {name}"}})
    assert check_locales.main(["--root", str(tmp_path)]) == 0


def test_missing_and_extra_keys_fail(tmp_path):
    loc = _locales(tmp_path)
    _write(loc, "en.json", {"a": "A", "b": "B"})
    _write(loc, "de.json", {"a": "A", "c": "C"})
    errors = check_locales.check_dir(loc)
    assert any("de.b: missing" in e for e in errors)
    assert any("de.c: not in en.json" in e for e in errors)


def test_placeholder_drift_and_blank_fail(tmp_path):
    loc = _locales(tmp_path)
    _write(loc, "en.json", {"a": "{count} items", "b": "{{n}} rows", "c": "Save"})
    _write(loc, "de.json", {"a": "{anzahl} Elemente", "b": "{n} Zeilen", "c": " "})
    errors = check_locales.check_dir(loc)
    assert len([e for e in errors if "placeholders" in e]) == 2
    assert any("de.c: blank translation" in e for e in errors)


def test_backticks_fail_in_every_catalogue(tmp_path):
    # Rendered as plain text, a Markdown code span shows its backticks (#189).
    loc = _locales(tmp_path)
    _write(loc, "en.json", {"a": {"b": "run `smpy x`"}, "c": "fine"})
    _write(loc, "de.json", {"a": {"b": "„smpy x“ ausführen"}, "c": "`gut`"})
    errors = check_locales.check_dir(loc)
    assert len([e for e in errors if "backtick" in e]) == 2
    assert any("en.json: en.a.b: contains a backtick" in e for e in errors)
    assert any("de.json: de.c: contains a backtick" in e for e in errors)
    assert check_locales.main(["--root", str(tmp_path)]) == 1


def test_a_lone_backtick_is_content_not_markdown(tmp_path):
    # Only a delimited span is Markdown; a single backtick is text to show.
    loc = _locales(tmp_path)
    _write(loc, "en.json", {"a": "Press the ` key", "b": "it`s"})
    _write(loc, "de.json", {"a": "Drücke die Taste `", "b": "es`s"})
    assert check_locales.check_dir(loc) == []


def test_repo_catalogues_pass():
    repo = Path(__file__).resolve().parents[2]
    assert check_locales.main(["--root", str(repo)]) == 0
