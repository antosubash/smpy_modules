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
   repo (news' ``pagebuilder`` extra) must have a ``>=`` floor and a
   ``# floor: <reason>`` comment, on its line or in the comment block directly
   above it, saying why that version. The rule cannot know which sibling
   version first shipped what the module uses, and it does not compare the
   floor with the lockstep version: ``bump_version.py`` never rewrites
   specifiers, so any lag rule would fail lint on an ordinary release. What it
   does is make nobody add or keep a floor without writing down why — news'
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
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
PAGES_ALLOWLIST: frozenset[str] = frozenset()
FRAMEWORK_PREFIX = "simple-module-"  # canonical form of simple_module_* / Simple.Module-*
NPM_SCOPE = "@simple-module-py/"
NPM_DEP_KEYS = ("dependencies", "peerDependencies", "devDependencies", "optionalDependencies")
# One concrete semver version, which is all an npm range of one comparator
# without an operator (or with "=") admits: "1.2.3", "=1.2.3", "v1.2.3-rc.1".
NPM_VERSION = re.compile(
    r"^=?\s*v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
)
# npm:<name>@<range> — an alias, under any dependency name.
NPM_ALIAS = re.compile(r"^npm:((?:@[^/@\s]+/)?[^@\s]+)(?:@(.*))?$")
FLOOR_COMMENT = re.compile(r"#\s*floor:\s*\S")
NOT_A_PAGE = re.compile(r"\.(test|spec|stories)\.tsx$")
# Comments and string/template literals, removed before looking for exports.
JS_NOISE = re.compile(
    r"//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`",
    re.DOTALL,
)
EXPORT_DEFAULT = re.compile(r"\bexport\s+default\b")
EXPORT_LIST = re.compile(r"\bexport\s*\{([^}]*)\}")


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


def _pins_exactly(req: Requirement) -> bool:
    """``===X`` or ``==X``; ``==0.0.*`` is a prefix match, i.e. a range."""
    return any(
        s.operator == "===" or (s.operator == "==" and not s.version.endswith("*"))
        for s in req.specifier
    )


def check_python_pins(pyproject: Path, root: Path) -> list[str]:
    data = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    errors = []
    for raw in _requirements(data.get("project", {}), data.get("dependency-groups", {})):
        req = _parse(raw)
        if req is None or not canonicalize_name(req.name).startswith(FRAMEWORK_PREFIX):
            continue
        if _pins_exactly(req):
            errors.append(
                f"{_rel(pyproject, root)}: '{raw}' pins exactly; a published module "
                "takes a range (CLAUDE.md pin policy)"
            )
    return errors


def _npm_target(name: str, spec: str) -> tuple[str, str]:
    """The package a dependency really resolves to, and its range."""
    spec = spec.strip()
    if spec.startswith("workspace:"):
        spec = spec.removeprefix("workspace:").strip()
    alias = NPM_ALIAS.match(spec)
    if alias:
        return alias.group(1), (alias.group(2) or "").strip()
    return name, spec


def _npm_exact(spec: str) -> bool:
    """A range that admits a single version: one comparator, no operator."""
    sets = [s.strip() for s in spec.split("||")]
    if len(sets) != 1:
        return False  # a union of alternatives
    comparators = re.sub(r"^=\s+", "=", sets[0]).split()
    return len(comparators) == 1 and bool(NPM_VERSION.match(comparators[0]))


def check_npm_pins(package_json: Path, root: Path) -> list[str]:
    data = json.loads(package_json.read_text(encoding="utf-8"))
    errors = []
    for key in NPM_DEP_KEYS:
        for name, spec in data.get(key, {}).items():
            target, rng = _npm_target(name, str(spec))
            if target.startswith(NPM_SCOPE) and _npm_exact(rng):
                errors.append(
                    f"{_rel(package_json, root)}: {key}['{name}'] = '{spec}' pins exactly; "
                    "a published module takes a range (CLAUDE.md pin policy)"
                )
    return errors


def _has_default_export(source: str) -> bool:
    code = JS_NOISE.sub(" ", source)
    if EXPORT_DEFAULT.search(code):
        return True
    for names in EXPORT_LIST.findall(code):  # export { X as default } / { default } from
        for spec in names.split(","):
            if spec.split() and spec.split()[-1] == "default":
                return True
    return False


def check_pages(root: Path, allowlist: frozenset[str] = PAGES_ALLOWLIST) -> list[str]:
    errors = []
    for path in sorted(root.glob("modules/*/*/pages/**/*")):
        rel = _rel(path, root)
        if not path.is_file() or rel in allowlist:
            continue
        if path.suffix != ".tsx" or NOT_A_PAGE.search(path.name):
            why = "is not an Inertia page (.tsx, not a test or story)"
        elif not _has_default_export(path.read_text(encoding="utf-8")):
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


def check_sibling_floors(pyproject: Path, root: Path, siblings: set[str]) -> list[str]:
    text = pyproject.read_text(encoding="utf-8")
    project = tomlkit.parse(text).get("project", {})
    own = canonicalize_name(str(project.get("name", "")))
    errors = []
    for raw in _requirements(project, {}):
        req = _parse(raw)
        if req is None or canonicalize_name(req.name) not in siblings - {own}:
            continue
        where = f"{_rel(pyproject, root)}: '{raw}'"
        if not any(s.operator == ">=" for s in req.specifier):
            errors.append(f"{where} has no >= floor; give it a deliberate one")
        elif not _has_floor_comment(text.splitlines(), str(raw)):
            errors.append(
                f"{where}: a floor on a sibling module needs a '# floor: <reason>' comment "
                "(on the line or directly above) naming what that version first shipped"
            )
    return errors


def check(root: Path) -> list[str]:
    pyprojects = sorted(root.glob("modules/*/pyproject.toml"))
    siblings = {
        canonicalize_name(str(tomlkit.parse(p.read_text(encoding="utf-8"))["project"]["name"]))
        for p in pyprojects
    }
    errors: list[str] = []
    for p in pyprojects:
        errors += check_python_pins(p, root)
        errors += check_sibling_floors(p, root, siblings)
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
