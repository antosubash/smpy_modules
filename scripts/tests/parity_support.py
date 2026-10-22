"""Compare helpers that are copied between modules, rather than imported (#127).

A published module must not import a sibling optional module, so a few helpers
exist in two to four copies — and copies drift: news' redirect lookup gained a
published check that pagebuilder's did not, and nothing failed. This is what
makes that fail.

Each copy is reduced to its *code*: comments and docstrings go (they describe
the module they live in and are allowed to say different things), formatting is
normalised, and the names that differ only because the module does — a settings
class, a table, a package — are mapped onto one spelling. What is left has to
match, declaration by declaration.

A declaration that is *meant* to differ is listed with the reason it does,
either as ``differ`` (every copy has it, the bodies may disagree) or as one
copy's ``own`` (only that copy has it). Both are checked for staleness: an
allowance whose bodies now agree, or that names something no longer there,
fails too, so the list cannot rot into a blanket exemption.
"""

from __future__ import annotations

import ast
import copy
import difflib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import ts_tokens

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Copy:
    """One copy of a helper file.

    ``rename`` maps an identifier in this copy onto the family's canonical
    spelling, applied to whole words of the normalised code. ``own`` names the
    declarations only this copy has, each with the reason; another copy that
    gains one fails. ``messages`` are the string literals (or an f-string's
    literal parts) that name this copy's module, masked before comparing —
    every other string, a protocol constant above all, is compared as written.
    """

    path: str
    rename: Mapping[str, str] = field(default_factory=dict)
    own: Mapping[str, str] = field(default_factory=dict)
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class Family:
    """Copies of one helper, and what they are allowed to disagree about.

    ``shared=None`` means *every* declaration not allowed for below has to be in
    every copy and match — the file is a copy as a whole. A tuple restricts the
    comparison to those names (``Class.method`` reaches into a class), for files
    that only partly overlap.
    """

    name: str
    copies: tuple[Copy, ...]
    differ: Mapping[str, str] = field(default_factory=dict)
    shared: tuple[str, ...] | None = None

    @property
    def is_typescript(self) -> bool:
        return self.copies[0].path.endswith((".ts", ".tsx"))


# --- Python -------------------------------------------------------------------


class _Normalise(ast.NodeTransformer):
    def __init__(self, messages: tuple[str, ...]) -> None:
        self.messages = messages

    def visit(self, node: ast.AST) -> ast.AST:
        """Drop the docstring of every function and class before visiting it."""
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if (
                isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
        return super().visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, str) and node.value in self.messages:
            return ast.Constant("<message>")
        return node


def _assigned_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _python_decls(source: str) -> dict[str, ast.AST]:
    decls: dict[str, ast.AST] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            decls[node.name] = node
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        decls[f"{node.name}.{item.name}"] = item
        for name in _assigned_names(node):
            decls[name] = node
    return decls


def _python_code(node: ast.AST, messages: tuple[str, ...]) -> str:
    return ast.unparse(_Normalise(messages).visit(copy.deepcopy(node)))


def _string_literals(source: str) -> set[str]:
    """Every string constant, f-string parts included, so a stale message shows."""
    return {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


# --- TypeScript ---------------------------------------------------------------

_TS_DECL = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\*?|const|let|var|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)"
)


def _ts_decls(source: str) -> dict[str, str]:
    """Top-level declarations, keyed by name, each with its full text.

    A declaration starts at column 0 and runs to the next line that does;
    a closing bracket at column 0 still belongs to the one above it.
    """
    code = ts_tokens.strip_comments(source)
    chunks: list[list[str]] = []
    for line in code.splitlines():
        if not line.strip():
            continue
        if line[0] not in " \t}])" and not line.startswith("import "):
            chunks.append([line])
        elif chunks and not line.startswith("import "):
            chunks[-1].append(line)
    decls: dict[str, str] = {}
    for chunk in chunks:
        match = _TS_DECL.match(chunk[0])
        name = match.group(1) if match else chunk[0]
        decls[name] = "\n".join(chunk)
    return decls


# --- comparison ---------------------------------------------------------------


def _rename(code: str, rename: Mapping[str, str]) -> str:
    for old, new in rename.items():
        code = re.sub(rf"(?<![\w$]){re.escape(old)}(?![\w$])", new, code)
    return code


def normalised(family: Family, member: Copy) -> dict[str, str]:
    """Every declaration of one copy, reduced to comparable code."""
    source = (REPO / member.path).read_text(encoding="utf-8")
    if family.is_typescript:
        raw = {name: ts_tokens.code(text) for name, text in _ts_decls(source).items()}
    else:
        raw = {
            name: _python_code(node, member.messages)
            for name, node in _python_decls(source).items()
        }
    rename = member.rename
    return {_rename(name, rename): _rename(code, rename) for name, code in raw.items()}


def problems(family: Family) -> list[str]:
    """Everything wrong with one family: drift, missing copies, stale allowances."""
    decls = {m.path: normalised(family, m) for m in family.copies}
    found = _stale_allowances(family, decls)
    # An `own` entry is written as the copy spells it; compare it as renamed.
    owners: dict[str, list[str]] = {}
    for member in family.copies:
        for name in member.own:
            owners.setdefault(_rename(name, member.rename), []).append(member.path)
    if family.shared is not None:
        names = set(family.shared) | set(family.differ)
    else:
        names = {n for d in decls.values() for n in d if "." not in n}
    for name in sorted(names):
        if name in owners:
            others = [p for p in decls if p not in owners[name] and name in decls[p]]
            if others:
                found.append(
                    f"{name!r} is `own` to {', '.join(owners[name])}, "
                    f"but {', '.join(others)} has it too"
                )
            continue
        missing = [m.path for m in family.copies if name not in decls[m.path]]
        if missing:
            found.append(f"{name!r} is missing from {', '.join(missing)}")
            continue
        bodies = [decls[m.path][name] for m in family.copies]
        same = all(body == bodies[0] for body in bodies)
        if name in family.differ:
            if same:
                found.append(f"{name!r} is allowed to differ, but every copy now agrees")
            continue
        first = family.copies[0].path
        for other in family.copies[1:]:
            if decls[other.path][name] != bodies[0]:
                found.append(_diff(name, first, other.path, bodies[0], decls[other.path][name]))
    return found


def _stale_allowances(family: Family, decls: dict[str, dict[str, str]]) -> list[str]:
    """`own` entries and masked messages that name something no longer there."""
    found: list[str] = []
    for member in family.copies:
        for name in sorted(member.own):
            if _rename(name, member.rename) not in decls[member.path]:
                found.append(f"{member.path}: `own` lists {name!r}, which is not there")
        if member.messages:
            strings = _string_literals((REPO / member.path).read_text(encoding="utf-8"))
            for message in member.messages:
                if message not in strings:
                    found.append(f"{member.path}: `messages` lists {message!r}, which is not there")
    return found


def _diff(name: str, a_path: str, b_path: str, a: str, b: str) -> str:
    lines = difflib.unified_diff(
        a.splitlines(), b.splitlines(), f"{a_path}::{name}", f"{b_path}::{name}", lineterm=""
    )
    return f"{name!r} has drifted:\n" + "\n".join(lines)
