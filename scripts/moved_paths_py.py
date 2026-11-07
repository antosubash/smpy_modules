"""The Python half of ``moved_paths.py``: the table each package's hook reads (#319).

Names are read with ``ast``, never by importing, so the generator runs on a
fake tree in the tests and on the v0.0.13 sources, which are not installed.
"""

from __future__ import annotations

import ast
import difflib
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from moved_paths_common import HOOK, Move, Package, guess

GETATTR_CALL = "moved_attribute(__name__, name)"


@dataclass
class Surface:
    defined: set[str] = field(default_factory=set)  # bound by def, class or assignment
    bound: set[str] = field(default_factory=set)  # defined, plus imported names


def _targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Tuple | ast.List):
        return [n for e in node.elts for n in _targets(e)]
    return []


def _statements(body: list[ast.stmt]):
    for node in body:  # also look inside top-level if / try (TYPE_CHECKING, fallbacks)
        if isinstance(node, ast.If | ast.Try):
            yield from _statements(node.body + node.orelse + getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                yield from _statements(handler.body)
        else:
            yield node


def surface(source: str) -> Surface:
    found = Surface()
    for node in _statements(ast.parse(source).body):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.defined.add(node.name)
        elif isinstance(node, ast.Assign):
            found.defined.update(n for t in node.targets for n in _targets(t))
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            found.defined.update(_targets(node.target))
        elif isinstance(node, ast.Import):
            found.bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.bound.update(a.asname or a.name for a in node.names if a.name != "*")
    found.bound |= found.defined
    return found


def dunder_all(source: str) -> list[str] | None:
    """The module's literal ``__all__``, if it has one."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and "__all__" in _targets(node.targets[0]):
            return sorted(ast.literal_eval(node.value))
    return None


def old_public(source: str, is_init: bool) -> list[str]:
    """What an old module exported: ``__all__``, else its public definitions.

    A package ``__init__`` also exported what it imported from its own package.
    """
    if (listed := dunder_all(source)) is not None:
        return listed
    tree = ast.parse(source)
    names = {n for n in surface(source).defined if not n.startswith("_")}
    if is_init:
        for node in _statements(tree.body):
            if isinstance(node, ast.ImportFrom) and node.level:
                names.update(a.asname or a.name for a in node.names if a.name != "*")
    return sorted(n for n in names if not n.startswith("_"))


def module_file(root: Path, pkg: Package, dotted: str) -> Path | None:
    """The file behind a dotted name inside ``pkg``, if it exists."""
    rel = Path(*dotted.split(".")[1:])
    if not rel.parts:
        return root / pkg.rel / "__init__.py"
    for path in (root / pkg.rel / rel.with_suffix(".py"), root / pkg.rel / rel / "__init__.py"):
        if path.is_file():
            return path
    return None


def index(root: Path, pkg: Package) -> dict[str, Surface]:
    """Every current module of the package and its names."""
    found = {}
    for path in sorted((root / pkg.rel).rglob("*.py")):
        rel = path.relative_to(root / pkg.rel).as_posix()
        if rel != HOOK:
            found[pkg.dotted(rel)] = surface(path.read_text(encoding="utf-8"))
    return found


def definition(source: str | None, name: str) -> str | None:
    """The top-level ``def``/``class``/assignment that binds ``name``, as source."""
    if source is None:
        return None
    for node in _statements(ast.parse(source).body):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if node.name == name:
                return ast.unparse(node)
        elif isinstance(node, ast.Assign | ast.AnnAssign) and name in _targets(
            node.targets[0] if isinstance(node, ast.Assign) else node.target
        ):
            return ast.unparse(node)
    return None


def _home(
    name: str,
    old: str,
    prefer: list[str],
    current: dict[str, Surface],
    old_source: str | None = None,
    source_of=None,
) -> str | None:
    """The current module that defines ``name``.

    A preferred one wins. Otherwise, when several modules define it, the one whose
    definition is closest to the old one: a shared name such as ``subscribe`` must
    not land on an unrelated function (``sm_billing.teardown.subscribe``). Last
    resorts are the old leaf name and the shortest path.
    """
    homes = [m for m, s in current.items() if name in s.defined]
    if not homes:
        return None
    leaf = old.rsplit(".", 1)[-1]
    was = definition(old_source, name)

    def likeness(m: str) -> float:
        now = definition(source_of(m), name) if source_of and was else None
        return difflib.SequenceMatcher(None, was, now).ratio() if was and now else 0.0

    homes.sort(
        key=lambda m: (m not in prefer, -likeness(m), m.rsplit(".", 1)[-1] != leaf, m.count("."), m)
    )
    if len(homes) > 1 and homes[0] not in prefer:
        print(
            f"note: {old}.{name} -> {homes[0]} ({likeness(homes[0]):.2f} like the old one;"
            f" also in {', '.join(homes[1:])})",
            file=sys.stderr,
        )
    return homes[0]


def build(root: Path, old_root: Path, pkg: Package, moves: list[Move], dirs: dict) -> dict:
    """The ``modules``/``packages``/``names``/``attributes``/``removed`` tables."""
    current = index(root, pkg)
    table: dict = {"modules": {}, "packages": {}, "names": {}, "attributes": {}, "removed": {}}
    py = [m for m in moves if m.package == pkg and m.old.endswith(".py")]
    exported: dict[str, list[str]] = {}

    def source_of(dotted: str) -> str | None:
        path = module_file(root, pkg, dotted)
        return path.read_text(encoding="utf-8") if path else None

    for move in py:
        old = pkg.dotted(move.old)
        is_init = move.old.endswith("__init__.py")
        old_source = (old_root / pkg.rel / move.old).read_text(encoding="utf-8")
        wanted = old_public(old_source, is_init)

        def home(n: str, candidates: list[str], old=old, old_source=old_source) -> str | None:
            return _home(n, old, candidates, current, old_source, source_of)

        exported[old] = wanted
        candidates = [
            pkg.dotted(p) for p in (move.new, guess(move, dirs)) if p and p.endswith(".py")
        ]
        candidates = [c for c in dict.fromkeys(candidates) if c in current]
        if old not in current and any(m.startswith(f"{old}.") for m in current):
            raise SystemExit(f"{old} is a namespace package with modules today; alias it by hand")
        if old in current:  # the old name is a real module again: it lends its lost names
            missing = [n for n in wanted if n not in current[old].bound]
            homes = {n: home(n, candidates) for n in missing}
            if found := {n: h for n, h in homes.items() if h}:
                table["attributes"][old] = found
            if lost := sorted(n for n, h in homes.items() if not h):
                table["removed"][old] = lost
            continue
        candidates.sort(key=lambda c: -sum(n in current[c].bound for n in wanted))
        primary = candidates[0] if candidates else None
        package_ok = not is_init or (primary and current_is_package(root, pkg, primary))
        if primary and package_ok and all(n in current[primary].bound for n in wanted):
            table["modules"][old] = primary
        else:
            homes = {
                n: (primary if primary and n in current[primary].bound else None) for n in wanted
            }
            homes |= {n: home(n, candidates) for n, h in homes.items() if not h}
            sources = [m for m in dict.fromkeys([primary, *homes.values()]) if m]
            table["modules"][old] = sources
            table["names"][old] = sorted(n for n, h in homes.items() if h)
            if lost := sorted(n for n, h in homes.items() if not h):
                table["removed"][old] = lost
        if is_init:
            table["packages"][old] = _prefix(root, pkg, move, py, dirs)
    while clashes := clobbers(table, current):
        for old, parent in clashes:
            if not isinstance(table["modules"].get(parent), str):
                raise SystemExit(
                    f"importing {old} would overwrite {parent}.{old.rpartition('.')[2]}"
                )
            # The old package stops being the new one and becomes a compat
            # package of its own, so its children's attributes land there.
            table["modules"][parent] = [table["modules"][parent]]
            table["names"][parent] = exported[parent]
    return {k: v for k, v in table.items() if v}


def clobbers(table: dict, current: dict[str, Surface]) -> list[tuple[str, str]]:
    """``(old child, old parent)`` where importing the child overwrites a real name.

    Importing ``a.b`` sets attribute ``b`` on whatever ``a`` resolves to, so an
    old child must not share its name with something the parent's target has.
    """
    errors = []
    for old, new in table["modules"].items():
        parent, _, leaf = old.rpartition(".")
        target = table["modules"].get(parent, parent if parent in current else None)
        if isinstance(target, list):
            taken = leaf in table["names"].get(parent, ())
        elif target in current:
            sub = f"{target}.{leaf}"
            taken = sub != new and (leaf in current[target].bound or sub in current)
        else:
            continue
        if taken:
            errors.append((old, parent))
    return errors


def current_is_package(root: Path, pkg: Package, dotted: str) -> bool:
    path = module_file(root, pkg, dotted)
    return path is not None and path.name == "__init__.py"


def _prefix(root: Path, pkg: Package, init: Move, py: list[Move], dirs: dict) -> str | None:
    """The new package an old one's children all moved into, if there is one."""
    old_dir = str(PurePosixPath(init.old).parent)
    new_dir = dirs.get((pkg, old_dir))
    if not new_dir or not (root / pkg.rel / new_dir / "__init__.py").is_file():
        return None
    for move in py:
        if move.old.startswith(f"{old_dir}/") and move.old != init.old:
            expected = new_dir + move.old[len(old_dir) :]
            if move.new != expected and not (move.new is None and _exists(root, pkg, expected)):
                return None
    return pkg.dotted(f"{new_dir}/__init__.py")


def _exists(root: Path, pkg: Package, rel: str) -> bool:
    return (root / pkg.rel / rel).is_file()
