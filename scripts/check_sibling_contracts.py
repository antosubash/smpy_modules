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
top level there (or a submodule of that name). ``from sm_ai import
contracts`` counts, and so does the string passed to
``importlib.import_module`` (directly or through a constant of the package),
which is how an optional extra is loaded. Names bound only under
``if TYPE_CHECKING:`` do not count as defined. A floor that is the next patch,
minor or major after the newest tag is the release being prepared, so it is
checked against the working tree. Any other floor with no tag of its own names
no release and fails.

Only ``contracts`` imports are checked: another module's internals are not an
interface (CLAUDE.md), and a name that moved there is a different problem.

Needs the release tags (``git fetch --tags``; CI checks out with
``fetch-depth: 0``). Exit 0 on success, 1 on any violation.
"""

from __future__ import annotations

import argparse
import functools
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from check_rules import _parse, _requirements
from contract_imports import imports, scan, top_level_names
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
WORKTREE = "working tree"


@dataclass(frozen=True)
class Module:
    root: Path  # modules/<dir>
    package: str  # top-level import package, from the simple_module entry point
    requirements: tuple[str, ...] = ()  # every dependency, extras included


def _modules(root: Path) -> dict[str, Module]:
    found = {}
    for pyproject in sorted(root.glob("modules/*/pyproject.toml")):
        project = tomlkit.parse(pyproject.read_text(encoding="utf-8"))["project"]
        entry = next(iter(project.get("entry-points", {}).get("simple_module", {}).values()), None)
        if entry is None:
            continue
        dist = canonicalize_name(str(project["name"]))
        found[dist] = Module(
            pyproject.parent, str(entry).split(".", 1)[0], tuple(_requirements(project, {}))
        )
    return found


def _tags(root: Path) -> dict[Version, str]:
    """Release versions and the tag that spells each (``v0.0.16-rc1`` parses as 0.0.16rc1)."""
    listed = subprocess.run(
        ["git", "-C", str(root), "tag", "--list", "v*"], capture_output=True, text=True
    )
    out = listed.stdout.split() if listed.returncode == 0 else []  # not a clone: no tags
    tags = {}
    for tag in out:
        try:
            tags[Version(tag[1:])] = tag
        except InvalidVersion:
            continue
    return tags


@functools.cache
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


def _floor(req: Requirement) -> Version | None:
    floors = [Version(s.version) for s in req.specifier if s.operator == ">="]
    return max(floors) if floors else None


def _next_releases(newest: Version) -> set[Version]:
    major, minor, patch = (*newest.release, 0, 0)[:3]
    return {Version(f"{major}.{minor}.{patch + 1}"), Version(f"{major}.{minor + 1}.0"),
            Version(f"{major + 1}.0.0")}


def _ref(floor: Version, tags: dict[Version, str]) -> str | None:
    """The tag a floor names, the working tree for the release being prepared, else None.

    Only the next patch, minor or major after the newest stable tag counts as
    "being prepared", a prerelease of one included (``0.0.16rc1``, and ``0.0.16``
    once that rc is tagged): a floor of 0.0.60 while 0.0.15 is the newest tag is
    a typo that would make the module uninstallable, not a release the working
    tree stands for.
    """
    if floor in tags:
        return tags[floor]
    stable = [t for t in tags if not t.is_prerelease] or list(tags)
    if Version(floor.base_version) in _next_releases(max(stable)):
        return WORKTREE  # check() refuses an empty tag set first
    return None


def _missing(root: Path, ref: str, base: str, module: str, names: tuple[str, ...]) -> list[str]:
    """What of ``from module import names`` (or ``import module``) *ref* lacks."""
    source = _module_source(root, ref, base, module)
    if source is None:
        return [module]
    defined = top_level_names(source)
    if defined is None:  # a module __getattr__: any name may resolve
        return []
    return [
        f"{module}.{name}"
        for name in names
        if name != "*"
        and name not in defined
        and _module_source(root, ref, base, f"{module}.{name}") is None
    ]


def check(root: Path) -> list[str]:
    _read.cache_clear()  # one run reads each file once; a later run may see new tags or edits
    modules = _modules(root)
    tags = _tags(root)
    if not tags:
        return ["no v* release tags in this clone; run `git fetch --tags` (CI: fetch-depth: 0)"]
    errors = []
    for dependant in modules.values():
        scanned = scan(dependant.root / dependant.package)  # once, however many siblings
        for req in filter(None, map(_parse, dependant.requirements)):
            sibling = modules.get(canonicalize_name(req.name))
            floor = _floor(req)
            if sibling is None or sibling is dependant or floor is None:
                continue  # check_rules.py reports a sibling requirement without a floor
            where = f"{dependant.root.relative_to(root).as_posix()}: '{req}'"
            ref = _ref(floor, tags)
            if ref is None:
                errors.append(f"{where}: no release v{floor} exists (no tag, and not the next one)")
                continue
            base = sibling.root.relative_to(root).as_posix()
            missing: dict[str, list[str]] = {}
            for path, module, names in imports(scanned, f"{sibling.package}.contracts"):
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
        print(f"\nFAIL: {len(errors)} sibling floor problem(s).", file=sys.stderr)
        return 1
    print("Sibling floors ship every contract their dependants import.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
