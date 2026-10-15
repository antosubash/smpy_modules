"""Every translated console catalogue matches its module's English one.

Rules for each ``modules/<name>/<package>/locales/<lang>.json`` other than
``en.json``:
  * The key tree is exactly ``en.json``'s — no key missing, none extra.
    A missing key falls back to English at runtime (the framework layers each
    locale over the default), so this is about drift, not crashes: a renamed
    English key would otherwise leave a dead German one and an untranslated
    string, and nothing would say so.
  * Each string carries the same interpolation placeholders (``{name}``,
    ``{{name}}``) as its English source. A translator who drops or renames one
    renders a literal brace or loses the value.
  * No translated string is blank where the English is not.

Exit 0 if all pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SOURCE = "en.json"
PLACEHOLDER = re.compile(r"\{\{?\s*[\w.]+\s*\}?\}")


def compare(en: object, other: object, where: str) -> list[str]:
    if isinstance(en, dict):
        if not isinstance(other, dict):
            return [f"{where}: expected an object"]
        errors = [f"{where}.{key}: missing" for key in en if key not in other]
        errors += [f"{where}.{key}: not in {SOURCE}" for key in other if key not in en]
        for key in en:
            if key in other:
                errors += compare(en[key], other[key], f"{where}.{key}")
        return errors
    if not isinstance(other, str):
        return [f"{where}: expected a string"]
    errors = []
    expected, found = PLACEHOLDER.findall(str(en)), PLACEHOLDER.findall(other)
    if sorted(expected) != sorted(found):
        errors.append(f"{where}: placeholders {expected} != {found}")
    if str(en).strip() and not other.strip():
        errors.append(f"{where}: blank translation")
    return errors


def check_dir(locales: Path) -> list[str]:
    source = locales / SOURCE
    if not source.is_file():
        return []
    en = json.loads(source.read_text(encoding="utf-8"))
    errors: list[str] = []
    for path in sorted(locales.glob("*.json")):
        if path.name == SOURCE:
            continue
        try:
            other = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue
        errors += [f"{path}: {e}" for e in compare(en, other, path.stem)]
    return errors


def discover(root: Path) -> list[Path]:
    """Every module's catalogues, plus the host's vendored ``packages/*/locales``."""
    found = [*(root / "modules").glob("*/*/locales"), *(root / "packages").glob("*/locales")]
    return sorted(path for path in found if path.is_dir() and "node_modules" not in path.parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    errors: list[str] = []
    for locales in discover(args.root):
        errors.extend(check_dir(locales))

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\nFAIL: {len(errors)} catalogue violation(s).", file=sys.stderr)
        return 1
    print("All locale catalogues match en.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
