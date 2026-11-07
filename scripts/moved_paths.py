"""Deprecated aliases for the paths the 0.0.14 module layout moved (#319).

``--generate`` runs once, from ``git diff -M v0.0.13 v0.0.14``: it writes each
package's ``core/moved_paths.json`` (read by the ``core/moved_paths.py`` import
hook) and a re-export stub at every old TypeScript or CSS path.

``--check`` runs in ``make lint`` and CI, without git history: the tables'
targets exist, every stub is what ``--generate`` wrote, a stub re-exports
``default`` exactly when its file has one, the packages that lend old names
through ``__getattr__`` still do, and nothing in the repo imports an old path.

Exit 0 on success, 1 on any violation, printed to stderr.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import moved_paths_py as py
import moved_paths_ts as ts
from moved_paths_common import (
    NEW_REF,
    OLD_REF,
    REMOVE_IN,
    Package,
    dir_map,
    packages,
    parse_moves,
    read_table,
    write_table,
)
from moved_paths_imports import python_offenders, ts_offenders

ROOT = Path(__file__).resolve().parents[1]


def generate(root: Path, listing: str, old_root: Path) -> dict[Package, dict]:
    """Write every table and stub; ``old_root`` holds the old release's ``modules/``."""
    pkgs = packages(root)
    moves = parse_moves(listing, pkgs)
    dirs = dir_map(moves)
    for pkg in pkgs:  # last run's stubs go first, so they never count as a new home
        for path in (root / pkg.rel).rglob("*"):
            if ts.is_stub(path):
                path.unlink()
    new = ts.surfaces(root, {p: ts.sources(root, p) for p in pkgs})
    old_ts = {
        p: [m.old for m in moves if m.package == p and m.old.endswith(ts.TS_SUFFIXES)] for p in pkgs
    }
    old = ts.surfaces(old_root, old_ts)
    tables = {}
    for pkg in pkgs:
        table = {"remove_in": REMOVE_IN, **py.build(root, old_root, pkg, moves, dirs)}
        stubs, css, lost = ts.plan(pkg, moves, dirs, old[pkg], new[pkg])
        table |= {k: v for k, v in (("ts", stubs), ("css", css), ("ts_removed", lost)) if v}
        for rel, spec in stubs.items():
            _write(root / pkg.rel / rel, ts.render(rel, spec))
        for rel, target in css.items():
            _write(root / pkg.rel / rel, ts.render_css(rel, target))
        write_table(root, pkg, table)
        tables[pkg] = table
    return tables


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check_python(root: Path, pkg: Package, table: dict) -> list[str]:
    errors = []
    current = py.index(root, pkg)
    for old, new in table.get("modules", {}).items():
        if old in current:
            errors.append(f"{old} is a real module, so the alias would shadow it")
        for target in [new] if isinstance(new, str) else new:
            if target not in current:
                errors.append(f"{old} -> {target}, which does not exist")
        parent = old.rpartition(".")[0]
        if parent in current and not (
            py.current_is_package(root, pkg, parent) or "__path__" in current[parent].defined
        ):
            errors.append(f"{old}: its parent {parent} is a plain module; give it a __path__")
        for name in table.get("names", {}).get(old, []):
            if not any(name in current.get(t, py.Surface()).bound for t in new):
                errors.append(f"{old}.{name} is in none of {new}")
    for prefix in filter(None, table.get("packages", {}).values()):
        if not py.current_is_package(root, pkg, prefix):
            errors.append(f"package prefix {prefix} is not a package")
    for module, attrs in table.get("attributes", {}).items():
        path = py.module_file(root, pkg, module)
        text = path.read_text(encoding="utf-8") if path else ""
        if path is None or py.GETATTR_CALL not in text:
            errors.append(
                f"{module} lends {sorted(attrs)} but has no __getattr__ calling moved_attribute"
            )
        # `import *` reads __all__ (or the module dict) and never asks __getattr__
        # for a name it does not list, so a lent name must be in __all__.
        elif not set(attrs) <= set(py.dunder_all(text) or ()):
            errors.append(f"{module} lends {sorted(attrs)}; list them in its __all__")
        for name, target in attrs.items():
            if name not in current.get(target, py.Surface()).bound:
                errors.append(f"{module}.{name} -> {target}, which has no {name}")
    return errors


def _check_ts(root: Path, pkg: Package, table: dict, surf: dict[str, dict]) -> list[str]:
    errors = []
    stubs, css = table.get("ts", {}), table.get("css", {})
    for rel in sorted(stubs.keys() | css.keys()):
        path = root / pkg.rel / rel
        want = ts.render(rel, stubs[rel]) if rel in stubs else ts.render_css(rel, css[rel])
        if not path.is_file() or path.read_text(encoding="utf-8") != want:
            errors.append(f"{pkg.rel}/{rel}: not what --generate writes; rerun it")
    for rel, target in css.items():
        if not (root / pkg.rel / target).is_file():
            errors.append(f"{pkg.rel}/{rel}: {target} does not exist")
    for rel, spec in stubs.items():
        star, default = spec.get("star"), spec.get("default")
        for target in filter(
            None, [star, default, *spec.get("values", {}), *spec.get("types", {})]
        ):
            if target not in surf:
                errors.append(f"{pkg.rel}/{rel}: {target} does not exist")
        if star in surf and surf[star]["default"] and not default:
            errors.append(
                f"{pkg.rel}/{rel}: {star} has a default export the stub does not re-export"
            )
        if default in surf and not surf[default]["default"]:
            errors.append(f"{pkg.rel}/{rel}: {default} has no default export")
        for group in ("values", "types"):
            for target, names in spec.get(group, {}).items():
                exports = surf.get(target, {}).get("exports", {})
                for name in names:
                    kind = exports.get(name, {}).get("kind")
                    if kind is None or (group == "values" and kind == "type"):
                        errors.append(f"{pkg.rel}/{rel}: {target} exports no {group[:-1]} {name}")
    for path in (root / pkg.rel).rglob("*"):
        rel = path.relative_to(root / pkg.rel).as_posix()
        if ts.is_stub(path) and rel not in stubs and rel not in css:
            errors.append(f"{pkg.rel}/{rel}: a moved-path stub the table does not list")
    return errors


def check(root: Path) -> list[str]:
    pkgs = packages(root)
    tables = {p: read_table(root, p) for p in pkgs}
    surf = ts.surfaces(root, {p: ts.sources(root, p) for p in pkgs})
    errors = []
    for pkg, table in tables.items():
        errors += _check_python(root, pkg, table) + _check_ts(root, pkg, table, surf[pkg])
    return errors + python_offenders(root, pkgs, tables) + ts_offenders(root, pkgs)


def _old_tree(root: Path, ref: str, into: Path) -> Path:
    archive = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", ref, "modules"],
        capture_output=True,
        check=True,
    ).stdout
    tar_path = into / "old.tar"
    tar_path.write_bytes(archive)
    with tarfile.open(tar_path) as tar:
        tar.extractall(into, filter="data")
    (into / "node_modules").symlink_to(root / "node_modules")  # the old tsconfigs extend it
    return into


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.check:
        errors = check(root)
        for error in errors:
            print(error, file=sys.stderr)
        return 1 if errors else 0
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-status",
            "-M50",
            OLD_REF,
            NEW_REF,
            "--",
            "modules",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    with tempfile.TemporaryDirectory() as tmp:
        tables = generate(root, listing, _old_tree(root, OLD_REF, Path(tmp)))
    for pkg, table in tables.items():
        counts = {k: len(v) for k, v in table.items() if isinstance(v, dict)}
        print(f"{pkg.name}: {counts}")
        for old, names in {**table.get("removed", {}), **table.get("ts_removed", {})}.items():
            print(f"  removed from {old}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
