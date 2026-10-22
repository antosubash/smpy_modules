"""Enforce CLAUDE.md rules that were honour-system until #135.

1. **No exact pin on the framework or a sibling in a published module.**
   ``modules/*/pyproject.toml`` may not ``==`` (or ``===``) any
   ``simple_module_*`` requirement, and ``modules/*/package.json`` may not
   pin an ``@simple-module-py/*`` package to one exact version. A pin makes
   the module uninstallable in any host running a newer build. ``host/`` is
   exempt: it is never published and pins exactly on purpose.

2. **Nothing under ``modules/*/*/pages/`` but real Inertia pages.** The page
   name comes from the path through ``import.meta.glob``, so any stray file
   there registers a page. Every file must be a ``.tsx`` that is not a test or
   story and contains ``export default``. ``PAGES_ALLOWLIST`` names the
   exceptions (repo-relative paths); it is empty.

3. **A sibling floor is deliberate.** A requirement on another module of this
   repo (news' ``pagebuilder`` extra) must have a ``>=`` floor no more than
   ``MAX_FLOOR_LAG`` patch releases behind the lockstep version in the root
   ``pyproject.toml``, in the same ``major.minor`` series. A floor that is
   older on purpose carries a ``# floor: <reason>`` comment, on its line or in
   the comment block directly above it. The rule cannot know which sibling
   version first shipped what the module imports; what it can catch is a
   floor nobody has looked at for several releases, which is how news'
   ``>=0.0.8`` sat unexamined while the repo released up to 0.0.11.

The single-migration-head rule lives in ``check_migration_heads.py`` (#107).

Exit 0 on success, 1 on any violation, printed to stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
PAGES_ALLOWLIST: frozenset[str] = frozenset()
MAX_FLOOR_LAG = 2
NPM_SCOPE = "@simple-module-py/"
NPM_DEP_KEYS = ("dependencies", "peerDependencies", "devDependencies", "optionalDependencies")
# An npm range that admits one version only: "1.2.3", "=1.2.3", "v1.2.3".
NPM_EXACT = re.compile(r"^\s*=?\s*v?\d+\.\d+\.\d+\S*\s*$")
FLOOR_COMMENT = re.compile(r"#\s*floor:\s*\S")
NOT_A_PAGE = re.compile(r"\.(test|spec|stories)\.tsx$")


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _requirements(project: dict, groups: dict) -> Iterator[str]:
    yield from project.get("dependencies", [])
    for reqs in project.get("optional-dependencies", {}).values():
        yield from reqs
    for reqs in groups.values():
        yield from (r for r in reqs if isinstance(r, str))


def _parse(raw: str) -> Requirement | None:
    try:
        return Requirement(str(raw))
    except InvalidRequirement:
        return None


def check_python_pins(pyproject: Path, root: Path) -> list[str]:
    data = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    errors = []
    for raw in _requirements(data.get("project", {}), data.get("dependency-groups", {})):
        req = _parse(raw)
        if req is None or not req.name.replace("-", "_").startswith("simple_module_"):
            continue
        if any(s.operator in ("==", "===") for s in req.specifier):
            errors.append(
                f"{_rel(pyproject, root)}: '{raw}' pins exactly; a published module "
                "takes a range (CLAUDE.md pin policy)"
            )
    return errors


def check_npm_pins(package_json: Path, root: Path) -> list[str]:
    data = json.loads(package_json.read_text(encoding="utf-8"))
    errors = []
    for key in NPM_DEP_KEYS:
        for name, spec in data.get(key, {}).items():
            if name.startswith(NPM_SCOPE) and NPM_EXACT.match(str(spec)):
                errors.append(
                    f"{_rel(package_json, root)}: {key}['{name}'] = '{spec}' pins exactly; "
                    "a published module takes a range (CLAUDE.md pin policy)"
                )
    return errors


def check_pages(root: Path, allowlist: frozenset[str] = PAGES_ALLOWLIST) -> list[str]:
    errors = []
    for path in sorted(root.glob("modules/*/*/pages/**/*")):
        rel = _rel(path, root)
        if not path.is_file() or rel in allowlist:
            continue
        if path.suffix != ".tsx" or NOT_A_PAGE.search(path.name):
            why = "is not an Inertia page (.tsx, not a test or story)"
        elif "export default" not in path.read_text(encoding="utf-8"):
            why = "has no `export default` component"
        else:
            continue
        errors.append(
            f"{rel}: {why}; files under pages/ register as pages — move it to "
            "components/, hooks/ or utils/, or add it to PAGES_ALLOWLIST"
        )
    return errors


def _has_floor_comment(lines: list[str], needle: str) -> bool:
    for i, line in enumerate(lines):
        if needle not in line:
            continue
        if FLOOR_COMMENT.search(line):
            return True
        j = i - 1
        while j >= 0 and lines[j].lstrip().startswith("#"):
            if FLOOR_COMMENT.search(lines[j]):
                return True
            j -= 1
    return False


def check_sibling_floors(
    pyproject: Path, root: Path, siblings: set[str], current: Version
) -> list[str]:
    text = pyproject.read_text(encoding="utf-8")
    data = tomlkit.parse(text)
    project = data.get("project", {})
    own = str(project.get("name", ""))
    errors = []
    for raw in _requirements(project, {}):
        req = _parse(raw)
        if req is None or req.name not in siblings or req.name == own:
            continue
        floors = [Version(s.version) for s in req.specifier if s.operator == ">="]
        where = f"{_rel(pyproject, root)}: '{raw}'"
        if not floors:
            errors.append(f"{where} has no >= floor; give it a deliberate one")
            continue
        floor = max(floors)
        lag = current.micro - floor.micro
        stale = floor.release[:2] != current.release[:2] or lag > MAX_FLOOR_LAG
        if stale and not _has_floor_comment(text.splitlines(), str(raw)):
            errors.append(
                f"{where}: floor {floor} is more than {MAX_FLOOR_LAG} releases behind "
                f"{current}; raise it to the oldest version providing what this module "
                "uses, or justify it with a '# floor: <reason>' comment"
            )
    return errors


def check(root: Path) -> list[str]:
    pyprojects = sorted(root.glob("modules/*/pyproject.toml"))
    siblings = {
        str(tomlkit.parse(p.read_text(encoding="utf-8"))["project"]["name"]) for p in pyprojects
    }
    root_project = tomlkit.parse((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    current = Version(str(root_project["version"]))
    errors: list[str] = []
    for p in pyprojects:
        errors += check_python_pins(p, root)
        errors += check_sibling_floors(p, root, siblings, current)
    for p in sorted(root.glob("modules/*/package.json")):
        errors += check_npm_pins(p, root)
    errors += check_pages(root)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    errors = check(args.root)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\nFAIL: {len(errors)} rule violation(s).", file=sys.stderr)
        return 1
    print("CLAUDE.md rules OK (pins, pages/, sibling floors).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
