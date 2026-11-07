"""``moved_paths.py --check``: nothing in the repo imports an old path (#319).

The aliases are for downstream hosts. Inside the repo an old path must stay an
error: a relative import that lands in a stub directory would resolve silently
now, and the code would break again when the aliases go in 0.0.17.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

from check_rules import JS_NOISE
from moved_paths_common import HOOK, Package
from moved_paths_ts import is_stub

_SPECIFIER = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(['"])([^'"\n]+)\1""")
_PROBES = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")
_SKIP_PARTS = {"node_modules", "dist", "versions", "__pycache__"}


def _files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    found = []
    for top in ("modules", "host", "scripts"):
        for path in (root / top).rglob("*"):
            if path.suffix in suffixes and not _SKIP_PARTS.intersection(path.parts):
                found.append(path)
    return sorted(found)


def _owner(path: Path, root: Path, pkgs: list[Package]) -> tuple[Package, str] | None:
    rel = path.relative_to(root).as_posix()
    for pkg in pkgs:
        if rel.startswith(f"{pkg.rel}/"):
            return pkg, rel[len(pkg.rel) + 1 :]
    return None


def _imported(tree: ast.AST, here: str | None) -> list[tuple[int, str]]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                if here is None:
                    continue
                base = here.split(".")[: len(here.split(".")) - node.level + 1]
                module = ".".join([*base, module] if module else base)
            names.append((node.lineno, module))
            names += [(node.lineno, f"{module}.{a.name}") for a in node.names]
    return names


def python_offenders(root: Path, pkgs: list[Package], tables: dict[Package, dict]) -> list[str]:
    exact: set[str] = set()
    prefixes: list[str] = []
    for table in tables.values():
        exact |= set(table.get("modules", {}))
        exact |= {f"{m}.{a}" for m, attrs in table.get("attributes", {}).items() for a in attrs}
        prefixes += [f"{p}." for p in table.get("packages", {})]
    errors = []
    for path in _files(root, (".py",)):
        owner = _owner(path, root, pkgs)
        if owner and owner[1] == HOOK:
            continue
        here = None
        if owner:
            dotted = owner[0].dotted(owner[1])
            here = dotted if path.name == "__init__.py" else dotted.rpartition(".")[0]
        for line, name in _imported(ast.parse(path.read_text(encoding="utf-8")), here):
            if name in exact or name.startswith(tuple(prefixes)):
                errors.append(f"{path.relative_to(root)}:{line}: imports the old path {name}")
    return errors


def _npm_names(root: Path, pkgs: list[Package]) -> dict[str, Package]:
    names = {}
    for pkg in pkgs:
        manifest = root / "modules" / pkg.module / "package.json"
        if manifest.is_file():
            names[json.loads(manifest.read_text(encoding="utf-8"))["name"]] = pkg
    return names


def _resolve(spec: str, path: Path, root: Path, owner, npm: dict[str, Package]) -> Path | None:
    if spec.startswith("."):
        base = path.parent / spec
    elif spec.startswith("@/") and owner:
        base = root / owner[0].rel / spec[2:]
    elif (scope := "/".join(spec.split("/")[:2])) in npm:
        base = root / npm[scope].rel / spec[len(scope) + 1 :]
    else:
        return None
    for probe in _PROBES:
        candidate = Path(os.path.normpath(f"{base}{probe}"))
        if candidate.is_file():
            return candidate
    return None


def ts_offenders(root: Path, pkgs: list[Package]) -> list[str]:
    npm = _npm_names(root, pkgs)
    errors = []
    for path in _files(root, (".ts", ".tsx", ".mts")):
        if is_stub(path):
            continue
        text = path.read_text(encoding="utf-8")
        code = JS_NOISE.sub(lambda m: m.group(0) if m.group(0)[0] in "'\"`" else " ", text)
        owner = _owner(path, root, pkgs)
        for match in _SPECIFIER.finditer(code):
            target = _resolve(match.group(2), path, root, owner, npm)
            if target is not None and target.suffix in (".ts", ".tsx", ".css") and is_stub(target):
                line = code.count("\n", 0, match.start()) + 1
                errors.append(
                    f"{path.relative_to(root)}:{line}: imports the old path {match.group(2)}"
                )
    return errors
