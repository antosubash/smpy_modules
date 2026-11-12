"""Refuse a deep frontend import into another module's package (#337).

A module's TypeScript is public only through its package's ``exports`` map:
``@simple-module-py/<module>`` (its ``index.ts``) and any subpath the map
declares, such as pagebuilder's ``./widgets-base.css``. Anything else is a
file path, and importing one makes every internal move a breaking change;
that is why the 0.0.14 layout move needed hundreds of re-export stubs (#319).

Refused, in ``modules/*`` and ``host/client_app``:

* ``@simple-module-py/<module>/<sub>`` for a module of this repo, unless
  ``./<sub>`` is a key of that module's ``exports`` (a module's own files
  included: they import each other relatively);
* ``@simple-module-py/<module>`` for a module that declares no ``"."`` export;
* a relative path that leaves the importing module for ``modules/<other>/``,
  or reaches ``modules/`` from the host.

``import.meta.glob`` is not an import and is not checked: pagebuilder's
``puck-blocks.ts`` and the host's ``blocks.ts`` find files by name on purpose.
The moved-path stubs re-export within their own package, so the rule never
meets them.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPE = "@simple-module-py/"
CODE_SUFFIXES = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs"}
SKIP_PARTS = {"node_modules", "dist", "__pycache__"}
SKIP_NAMES = {"modules.generated.ts", "modules.generated.css"}

# Comments (blanked, newlines kept) and string/template literals (kept).
_JS_NOISE = re.compile(
    r"//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`",
    re.DOTALL,
)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# `from`, side-effect `import`, `import(`, `require(` and the test runner's
# module calls (`vi.mock(`, `vi.importActual(`): a mock names a path as surely
# as an import does.
_SPECIFIER = re.compile(
    r"""(?:\bfrom\s*|(?<![.\w])import\s*\(\s*|(?<![.\w])import\s+|\brequire\s*\(\s*"""
    r"""|\b(?:vi|jest)\.\w+\s*\(\s*)(['"])([^'"\n]+)\1"""
)
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?(['"])([^'"\n]+)\1""")

# (repo-relative file, specifier) -> why it may stay. Keep it empty.
ALLOWLIST: dict[tuple[str, str], str] = {}


def _packages(root: Path) -> dict[str, tuple[str, set[str]]]:
    """npm name -> (module directory name, the keys of its ``exports``)."""
    found = {}
    for manifest in sorted((root / "modules").glob("*/package.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        exports = data.get("exports")
        if isinstance(exports, str):
            keys = {"."}
        elif isinstance(exports, dict):
            keys = set(exports)
        else:
            keys = set()
        found[data["name"]] = (manifest.parent.name, keys)
    return found


def _files(root: Path) -> list[Path]:
    found = []
    for top in (root / "modules", root / "host" / "client_app"):
        for path in top.rglob("*"):
            if (
                path.suffix in CODE_SUFFIXES | {".css"}
                and path.name not in SKIP_NAMES
                and not SKIP_PARTS.intersection(path.relative_to(root).parts)
                and path.is_file()
            ):
                found.append(path)
    return sorted(found)


def _specifiers(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".css":
        code = _CSS_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        pattern = _CSS_IMPORT
    else:
        code = _JS_NOISE.sub(
            lambda m: (
                m.group(0) if m.group(0)[0] in "'\"`" else "\n" * m.group(0).count("\n") or " "
            ),
            text,
        )
        pattern = _SPECIFIER
    return [(code.count("\n", 0, m.start()) + 1, m.group(2)) for m in pattern.finditer(code)]


def _module_of(path: Path, root: Path) -> str | None:
    """The ``modules/<name>`` a path lies in, ``""`` for anything else in the repo."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    return parts[1] if len(parts) > 2 and parts[0] == "modules" else ""


def _problem(spec: str, path: Path, root: Path, packages: dict) -> str | None:
    if spec.startswith(SCOPE):
        name = "/".join(spec.split("/")[:2])
        if name not in packages:
            return None  # the framework's packages (`ui`, `i18n`, …) are not ours to police
        sub = spec[len(name) :]
        exports = packages[name][1]
        if not sub:
            return None if "." in exports else f"{name} declares no '.' export"
        if f".{sub}" in exports:
            return None
        return f"deep import into {name}; import from '{name}' (its index.ts) instead"
    if spec.startswith("."):
        here = _module_of(path, root)
        target = _module_of(Path(os.path.normpath(path.parent / spec)), root)
        if target and target != here:
            npm = next((n for n, (d, _) in packages.items() if d == target), target)
            return f"relative import into modules/{target}/; import from '{npm}' instead"
    return None


def check(root: Path = ROOT) -> list[str]:
    packages = _packages(root)
    errors = []
    for path in _files(root):
        rel = path.relative_to(root).as_posix()
        for line, spec in _specifiers(path):
            problem = _problem(spec, path, root, packages)
            if problem and (rel, spec) not in ALLOWLIST:
                errors.append(f"{rel}:{line}: {problem}")
    return errors


def main() -> int:
    errors = check()
    for error in errors:
        print(error)
    if errors:
        print(
            f"\n{len(errors)} deep import(s) into another module's package. Export what you "
            "need from that module's index.ts (or its package.json exports) instead (#337).",
            file=sys.stderr,
        )
        return 1
    print("ok: no deep imports between module packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
