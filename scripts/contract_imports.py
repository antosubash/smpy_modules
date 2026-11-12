"""What a package imports from a sibling's ``contracts``, and what a module defines.

The AST half of ``check_sibling_contracts.py`` (#333), kept apart so the check
itself reads as the rule: which floor, which ref, what is missing.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path


def _is_contract(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _string_constants(tree: ast.Module) -> Iterator[tuple[str, str]]:
    """(name, value) for each module-level ``NAME = "…"`` or ``NAME: Final = "…"``."""
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                yield target.id, value.value


_LOADERS = frozenset({"import_module", "__import__", "find_spec"})


def _loader_aliases(tree: ast.Module) -> set[str]:
    """The bare names a loader is called by here: ``from importlib import
    import_module as im`` adds ``im``. An aliased module (``import importlib as
    il``) needs nothing: ``il.import_module`` is still matched by attribute."""
    names = set(_LOADERS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("importlib", "importlib.util"):
            names.update(a.asname for a in node.names if a.asname and a.name in _LOADERS)
    return names


def _module_argument(call: ast.Call) -> ast.expr | None:
    """The module-name argument: the first positional one, or ``name=``."""
    if call.args:
        return call.args[0]
    return next((k.value for k in call.keywords if k.arg == "name"), None)


def _import_module_targets(
    tree: ast.Module, constants: dict[str, set[str]], skip: set[int]
) -> Iterator[str]:
    """String targets of ``import_module(...)`` / ``__import__(...)`` / ``find_spec(...)`` calls.

    A literal argument (positional or ``name=``), or a constant bound to one
    anywhere in the package, named bare (``_CONTRACT``) or through its module
    (``constants.X``): how an optional extra is loaded. A loader imported under
    another name counts too. Other strings are not imports, however much they
    look like a module path. ``find_spec`` counts because it imports every
    parent of a dotted name (``find_spec("a.b.c")`` runs ``a.b``).
    """
    local = dict(_string_constants(tree))
    bare = _loader_aliases(tree)
    for node in ast.walk(tree):
        if id(node) in skip or not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr not in _LOADERS:
                continue
        elif not (isinstance(func, ast.Name) and func.id in bare):
            continue
        arg = _module_argument(node)
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield arg.value
        elif isinstance(arg, ast.Name) and arg.id in local:
            yield local[arg.id]  # a bare name is this file's constant when it has one
        elif isinstance(arg, (ast.Name, ast.Attribute)):
            yield from constants.get(arg.id if isinstance(arg, ast.Name) else arg.attr, ())


# (file, module, names, is "from module import names")
_Record = tuple[Path, str, tuple[str, ...], bool]


def scan(package_dir: Path) -> tuple[_Record, ...]:
    """Every absolute import and ``import_module``/``find_spec`` string in non-test code.

    One record per import, parsed once; ``imports`` filters them per sibling.
    """
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(package_dir.rglob("*.py"))
        if "tests" not in path.relative_to(package_dir).parts and not path.name.startswith("test_")
    }
    constants: dict[str, set[str]] = {}
    for tree in trees.values():
        for name, value in _string_constants(tree):
            constants.setdefault(name, set()).add(value)
    found: list[_Record] = []
    for path, tree in trees.items():
        type_only = {  # imports a type checker sees and the interpreter never runs
            id(inner)
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and _is_type_checking(node.test)
            for stmt in node.body
            for inner in ast.walk(stmt)
        }
        for node in ast.walk(tree):
            if id(node) in type_only:
                continue
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.append((path, node.module, tuple(a.name for a in node.names), True))
            elif isinstance(node, ast.Import):
                found.extend((path, alias.name, (), False) for alias in node.names)
        targets = _import_module_targets(tree, constants, type_only)
        found.extend((path, target, (), False) for target in targets)
    return tuple(found)


def imports(
    scanned: tuple[_Record, ...], prefix: str
) -> Iterator[tuple[Path, str, tuple[str, ...]]]:
    """Yield (file, module, names) for each import in *scanned* of *prefix* or below it."""
    parent, _, leaf = prefix.rpartition(".")
    for path, module, names, from_import in scanned:
        if _is_contract(module, prefix):
            yield path, module, names
        elif from_import and module == parent and leaf in names:
            yield path, prefix, ()  # from sm_ai import contracts


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _target_names(target: ast.expr) -> Iterator[str]:
    """Names bound by an assignment target, tuple and starred unpacking included."""
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _target_names(element)
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)


def top_level_names(source: str) -> set[str] | None:
    """Names a module defines at top level, or None when any name may resolve.

    That is a module ``__getattr__`` or a ``from x import *``, whose names this
    scan cannot see.
    """
    names: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    names.update(_target_names(target))
            elif isinstance(node, ast.AnnAssign):
                names.update(_target_names(node.target))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".", 1)[0] for a in node.names)
            elif isinstance(node, ast.If):
                if not _is_type_checking(node.test):
                    visit(node.body)  # names bound only for type checkers do not import
                visit(node.orelse)
            elif isinstance(node, (ast.Try, ast.TryStar)):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                visit(node.body)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                if not isinstance(node, ast.While):
                    names.update(_target_names(node.target))
                visit(node.body)
                visit(node.orelse)

    visit(ast.parse(source).body)
    return None if names & {"__getattr__", "*"} else names
