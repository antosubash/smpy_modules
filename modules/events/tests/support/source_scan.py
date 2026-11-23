"""Small ``ast`` scans over the package's source, for rules a test enforces by reading code.

Each scan takes source text so it can be proven against a planted violation; ``package_sources``
yields the real files. Nothing here matches on text, so a different spelling of the same thing
(an alias, an augmented assignment, ``setattr``, a keyword in ``.values(...)``, a dict key) is
found too.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import sm_events


def package_sources() -> Iterator[tuple[str, str]]:
    """``(path relative to the package, source)`` of every module of ``sm_events``."""
    root = Path(sm_events.__file__).parent
    for path in sorted(root.rglob("*.py")):
        yield path.relative_to(root).as_posix(), path.read_text()


def _functions(tree: ast.AST) -> dict[int, str]:
    """Line -> name of the innermost function containing it (``<module>`` outside any)."""
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner[line] = node.name
    return owner


def _targets(node: ast.AST) -> Iterator[ast.expr]:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            yield from ast.walk(target) if isinstance(target, ast.Tuple) else [target]
    elif isinstance(node, ast.AugAssign) or (
        isinstance(node, ast.AnnAssign)
        and node.value is not None
        and not isinstance(node.target, ast.Name)  # ``name: int = ...`` in a class is a declaration
    ):
        yield node.target


def assignments_to(source: str, name: str) -> list[tuple[int, str]]:
    """Every place ``name`` is written: ``x.name = ...``, ``x.name += ...``, ``setattr(x, "name",
    ...)``, a ``name=`` keyword in any call (``.values(name=...)``) or a ``"name"`` dict key
    (``.values(**{"name": ...})``). ``(line, enclosing function)``. A class-level declaration
    (``name: int = counter()``) is not a write."""
    tree = ast.parse(source)
    owner = _functions(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        hit = False
        for target in _targets(node):
            hit |= (isinstance(target, ast.Attribute) and target.attr == name) or (
                isinstance(target, ast.Name) and target.id == name
            )
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == name
            ):
                hit = True
            hit |= any(k.arg == name for k in node.keywords)
        if isinstance(node, ast.Dict):
            hit |= any(isinstance(k, ast.Constant) and k.value == name for k in node.keys)
        if hit:
            line = getattr(node, "lineno", 0)
            found.append((line, owner.get(line, "<module>")))
    return found


def constructions_of(source: str, class_name: str) -> list[int]:
    """Lines that build or copy a ``class_name``: a call of the name, of any alias it was
    imported under, of ``module.class_name``, or ``replace(...)`` of one
    (``dataclasses.replace``)."""
    tree = ast.parse(source)
    aliases = {class_name}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            aliases |= {a.asname for a in node.names if a.name == class_name and a.asname}
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        named = (isinstance(func, ast.Name) and func.id in aliases) or (
            isinstance(func, ast.Attribute) and func.attr == class_name
        )
        replaced = (
            (isinstance(func, ast.Name) and func.id == "replace")
            or (isinstance(func, ast.Attribute) and func.attr == "replace")
        ) and any(
            isinstance(arg, ast.Name) and class_name.lower() in arg.id.lower()
            for arg in node.args[:1]
        )
        if named or replaced:
            lines.append(node.lineno)
    return lines
