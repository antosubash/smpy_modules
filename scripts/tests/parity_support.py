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

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Copy:
    """One copy of a helper file.

    ``rename`` maps an identifier in this copy onto the family's canonical
    spelling, applied to whole words of the normalised code. ``own`` names the
    declarations only this copy has, each with the reason.
    """

    path: str
    rename: Mapping[str, str] = field(default_factory=dict)
    own: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Family:
    """Copies of one helper, and what they are allowed to disagree about.

    ``shared=None`` means *every* declaration not allowed for below has to be in
    every copy and match — the file is a copy as a whole. A tuple restricts the
    comparison to those names (``Class.method`` reaches into a class), for files
    that only partly overlap.

    ``mask_strings`` replaces every string literal before comparing, for copies
    whose messages name their own module but whose logic must not differ.
    """

    name: str
    copies: tuple[Copy, ...]
    differ: Mapping[str, str] = field(default_factory=dict)
    shared: tuple[str, ...] | None = None
    mask_strings: bool = False

    @property
    def is_typescript(self) -> bool:
        return self.copies[0].path.endswith((".ts", ".tsx"))


# --- Python -------------------------------------------------------------------


class _Normalise(ast.NodeTransformer):
    def __init__(self, mask_strings: bool) -> None:
        self.mask_strings = mask_strings

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
        if self.mask_strings and isinstance(node.value, str):
            return ast.Constant("<str>")
        return node

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        return ast.Constant("<str>") if self.mask_strings else self.generic_visit(node)


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


def _python_code(node: ast.AST, mask_strings: bool) -> str:
    return ast.unparse(_Normalise(mask_strings).visit(copy.deepcopy(node)))


# --- TypeScript ---------------------------------------------------------------

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# A `//` that starts a line or follows whitespace. `https://` has a colon in
# front of it, so a URL in a string survives.
_LINE_COMMENT = re.compile(r"(^|\s)//.*$", re.MULTILINE)
_TS_DECL = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\*?|const|let|var|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)"
)
_PUNCTUATION = re.compile(r"\s*([(){}\[\],;:=<>+*/|&?!.])\s*")


def _ts_decls(source: str) -> dict[str, str]:
    """Top-level declarations, keyed by name, each with its full text.

    A declaration starts at column 0 and runs to the next line that does;
    a closing bracket at column 0 still belongs to the one above it.
    """
    code = _LINE_COMMENT.sub(r"\1", _BLOCK_COMMENT.sub("", source))
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


def _ts_code(text: str) -> str:
    """Whitespace- and trailing-comma-insensitive, so Biome's wrapping is noise."""
    flat = re.sub(r"\s+", " ", text)
    flat = re.sub(r",\s*([)\]}])", r"\1", flat)
    return _PUNCTUATION.sub(r"\1", flat).strip()


# --- comparison ---------------------------------------------------------------


def _rename(code: str, rename: Mapping[str, str]) -> str:
    for old, new in rename.items():
        code = re.sub(rf"(?<![\w$]){re.escape(old)}(?![\w$])", new, code)
    return code


def normalised(family: Family, member: Copy) -> dict[str, str]:
    """Every declaration of one copy, reduced to comparable code."""
    source = (REPO / member.path).read_text(encoding="utf-8")
    if family.is_typescript:
        raw = {name: _ts_code(text) for name, text in _ts_decls(source).items()}
    else:
        raw = {
            name: _python_code(node, family.mask_strings)
            for name, node in _python_decls(source).items()
        }
    rename = member.rename
    return {_rename(name, rename): _rename(code, rename) for name, code in raw.items()}


def problems(family: Family) -> list[str]:
    """Everything wrong with one family: drift, missing copies, stale allowances."""
    decls = {m.path: normalised(family, m) for m in family.copies}
    found: list[str] = []
    # An `own` entry is written as the copy spells it; compare it as renamed.
    own = {m.path: {_rename(n, m.rename) for n in m.own} for m in family.copies}
    for member in family.copies:
        for name in sorted(own[member.path]):
            if name not in decls[member.path]:
                found.append(f"{member.path}: `own` lists {name!r}, which is not there")
    allowed_own = set().union(*own.values())
    if family.shared is not None:
        names = set(family.shared) | set(family.differ)
    else:
        names = {n for d in decls.values() for n in d if "." not in n} - allowed_own
    for name in sorted(names):
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


def _diff(name: str, a_path: str, b_path: str, a: str, b: str) -> str:
    lines = difflib.unified_diff(
        a.splitlines(), b.splitlines(), f"{a_path}::{name}", f"{b_path}::{name}", lineterm=""
    )
    return f"{name!r} has drifted:\n" + "\n".join(lines)
