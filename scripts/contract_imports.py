"""What a package imports from a sibling's ``contracts``, and what a module defines.

The AST half of ``check_sibling_contracts.py`` (#333), kept apart so the check
itself reads as the rule: which floor, which ref, what is missing.
"""

from __future__ import annotations

import ast
import functools
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


def _import_module_targets(tree: ast.Module, constants: dict[str, set[str]]) -> Iterator[str]:
    """String targets of ``import_module(...)`` / ``__import__(...)`` calls.

    A literal argument, or a constant bound to one anywhere in the package,
    named bare (``_CONTRACT``) or through its module (``constants.X``): how an
    optional extra is loaded. Other strings are not imports, however much they
    look like a module path.
    """
    local = dict(_string_constants(tree))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in ("import_module", "__import__"):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield arg.value
        elif isinstance(arg, ast.Name) and arg.id in local:
            yield local[arg.id]  # a bare name is this file's constant when it has one
        elif isinstance(arg, (ast.Name, ast.Attribute)):
            yield from constants.get(arg.id if isinstance(arg, ast.Name) else arg.attr, ())


# (file, module, names, is "from module import names")
_Record = tuple[Path, str, tuple[str, ...], bool]


@functools.cache
def _scan(package_dir: Path) -> tuple[_Record, ...]:
    """Every absolute import and ``import_module`` string in a package's non-test modules.

    Independent of the prefix asked about, so ``check`` walks each tree once however
    many siblings the package requires.
    """
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(package_dir.rglob("*.py"))
        if "tests" not in path.relative_to(package_dir).parts
        and not path.name.startswith("test_")
    }
    constants: dict[str, set[str]] = {}
    for tree in trees.values():
        for name, value in _string_constants(tree):
            constants.setdefault(name, set()).add(value)
    found: list[_Record] = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.append((path, node.module, tuple(a.name for a in node.names), True))
            elif isinstance(node, ast.Import):
                found.extend((path, alias.name, (), False) for alias in node.names)
        found.extend((path, t, (), False) for t in _import_module_targets(tree, constants))
    return tuple(found)


def forget_scan() -> None:
    """Drop the scan cache (``check`` reads each package once per run)."""
    _scan.cache_clear()


def imports(package_dir: Path, prefix: str) -> Iterator[tuple[Path, str, tuple[str, ...]]]:
    """Yield (file, module, names) for each absolute import of *prefix* or below it."""
    parent, _, leaf = prefix.rpartition(".")
    for path, module, names, from_import in _scan(package_dir):
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

    visit(ast.parse(source).body)
    return None if names & {"__getattr__", "*"} else names
