"""A sibling floor must ship the contracts its dependant imports (#333).

``check_rules.py`` makes every requirement on another module of this repo
carry a ``>=`` floor and a ``# floor:`` comment, but it never compares the
floor with anything. Newsletter's ``simple_module_records>=0.0.13`` sat on a
release that had none of the ``sm_records.contracts`` modules newsletter
imports: a host with records 0.0.15 installed kept it, and newsletter failed
at boot with ``ImportError``.

This check reads every ``<sibling package>.contracts`` import in a module's
package (tests excluded) and requires that the floor release ships it: the
module file at tag ``v<floor>``, and every name imported from it defined at
top level there (or a submodule of that name). A dotted string naming a contract module
(``importlib.import_module("news.contracts.articles")``, how an optional
extra is loaded) counts as an import of it. A floor above the newest tag is
the release being prepared, so it is checked against the working tree. A floor
below the newest tag with no tag of its own names no release and fails.

Only ``contracts`` imports are checked: another module's internals are not an
interface (CLAUDE.md), and a name that moved there is a different problem.

Needs the release tags (``git fetch --tags``; CI checks out with
``fetch-depth: 0``). Exit 0 on success, 1 on any violation.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
WORKTREE = "working tree"
DOTTED = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)+")


@dataclass(frozen=True)
class Module:
    dist: str  # canonical distribution name
    root: Path  # modules/<dir>
    package: str  # top-level import package, from the simple_module entry point


def _modules(root: Path) -> dict[str, Module]:
    found = {}
    for pyproject in sorted(root.glob("modules/*/pyproject.toml")):
        project = tomlkit.parse(pyproject.read_text(encoding="utf-8"))["project"]
        entry = next(iter(project.get("entry-points", {}).get("simple_module", {}).values()), None)
        if entry is None:
            continue
        dist = canonicalize_name(str(project["name"]))
        found[dist] = Module(dist, pyproject.parent, str(entry).split(".", 1)[0])
    return found


def _requirements(pyproject: Path) -> Iterator[Requirement]:
    project = tomlkit.parse(pyproject.read_text(encoding="utf-8")).get("project", {})
    raws = list(project.get("dependencies", []))
    for reqs in project.get("optional-dependencies", {}).values():
        raws += list(reqs)
    for raw in raws:
        try:
            yield Requirement(str(raw))
        except InvalidRequirement:
            continue


def _tags(root: Path) -> set[Version]:
    out = subprocess.run(
        ["git", "-C", str(root), "tag", "--list", "v*"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    tags = set()
    for tag in out:
        try:
            tags.add(Version(tag[1:]))
        except InvalidVersion:
            continue
    return tags


def _imports(package_dir: Path, prefix: str) -> Iterator[tuple[Path, str, tuple[str, ...]]]:
    """Yield (file, module, names) for each absolute import under *prefix*."""
    for path in sorted(package_dir.rglob("*.py")):
        rel = path.relative_to(package_dir)
        if "tests" in rel.parts or path.name.startswith("test_"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module == prefix or node.module.startswith(prefix + "."):
                    yield path, node.module, tuple(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(prefix + "."):
                        yield path, alias.name, ()
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and DOTTED.fullmatch(node.value)
                and node.value.startswith(prefix + ".")
            ):
                # An optional contract loaded with importlib.import_module("…").
                yield path, node.value, ()


def _read(root: Path, ref: str, rel: str) -> str | None:
    if ref == WORKTREE:
        path = root / rel
        return path.read_text(encoding="utf-8") if path.is_file() else None
    shown = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{rel}"], capture_output=True, text=True
    )
    return shown.stdout if shown.returncode == 0 else None


def _module_source(root: Path, ref: str, base: str, module: str) -> str | None:
    rel = f"{base}/{module.replace('.', '/')}"
    source = _read(root, ref, f"{rel}.py")
    return source if source is not None else _read(root, ref, f"{rel}/__init__.py")


def _top_level_names(source: str) -> set[str] | None:
    """Names a module defines at top level, or None when ``__getattr__`` makes any name valid."""
    names: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".", 1)[0] for a in node.names)
            elif isinstance(node, ast.If):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)

    visit(ast.parse(source).body)
    return None if "__getattr__" in names else names


def _floor(req: Requirement) -> Version | None:
    floors = [Version(s.version) for s in req.specifier if s.operator == ">="]
    return max(floors) if floors else None


def _ref(floor: Version, tags: set[Version]) -> str | None:
    if floor in tags:
        return f"v{floor}"
    if not tags or floor > max(tags):
        return WORKTREE
    return None


def _missing(root: Path, ref: str, base: str, module: str, names: tuple[str, ...]) -> list[str]:
    """What of ``from module import names`` (or ``import module``) *ref* lacks."""
    source = _module_source(root, ref, base, module)
    if source is None:
        return [module]
    defined = _top_level_names(source)
    return [
        f"{module}.{name}"
        for name in names
        if defined is not None
        and name != "*"
        and name not in defined
        and _module_source(root, ref, base, f"{module}.{name}") is None
    ]


def check(root: Path) -> list[str]:
    modules = _modules(root)
    tags = _tags(root)
    if not tags:
        return ["no v* release tags in this clone; run `git fetch --tags` (CI: fetch-depth: 0)"]
    errors = []
    for dependant in modules.values():
        package_dir = dependant.root / dependant.package
        for req in _requirements(dependant.root / "pyproject.toml"):
            sibling = modules.get(canonicalize_name(req.name))
            floor = _floor(req)
            if sibling is None or sibling is dependant or floor is None:
                continue  # check_rules.py reports a sibling requirement without a floor
            where = f"{dependant.root.relative_to(root).as_posix()}: '{req}'"
            ref = _ref(floor, tags)
            if ref is None:
                errors.append(f"{where}: no release v{floor} exists (no tag)")
                continue
            base = sibling.root.relative_to(root).as_posix()
            missing: dict[str, list[str]] = {}
            for path, module, names in _imports(package_dir, f"{sibling.package}.contracts"):
                importer = path.relative_to(root).as_posix()
                for target in _missing(root, ref, base, module, names):
                    missing.setdefault(target, []).append(importer)
            for target, importers in sorted(missing.items()):
                more = f" (and {len(importers) - 1} more)" if len(importers) > 1 else ""
                errors.append(
                    f"{where}: {ref} does not ship {target}, imported by {importers[0]}{more}; "
                    "raise the floor"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    errors = check(args.root)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\nFAIL: {len(errors)} sibling floor(s) below what is imported.", file=sys.stderr)
        return 1
    print("Sibling floors ship every contract their dependants import.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
