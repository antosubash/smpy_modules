"""Enforce that magic strings (permissions, role names, Inertia pages, module
dependencies) are declared as named constants rather than inline literals.

Violation patterns — checked only in non-test, non-constants .py files:

  - RequiresPermission("...")       → use a PERM_* constant
  - registry.map_role("...", ...)   → use a ROLE_NAME constant
  - registry.add_group(..., [...])  → permission items must be constants
  - inertia.render("Module/Page")   → use a _PAGE_* constant
  - depends_on=[..., "Module", ...] → use a _MODULE_* constant

Usage:
    uv run python scripts/check_hardcoded_strings.py
    uv run python scripts/check_hardcoded_strings.py --root some/subdir
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

# Each rule is (pattern, message). The pattern is matched against each line;
# a match is a violation unless the file is excluded.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r'RequiresPermission\s*\(\s*"[a-z_]+\.[a-z_]+"'),
        "permission string literal in RequiresPermission() — use a PERM_* constant",
    ),
    (
        re.compile(r'registry\.map_role\s*\(\s*"[a-z_]+"'),
        "role name literal in registry.map_role() — use a ROLE_NAME constant",
    ),
    (
        re.compile(r'registry\.add_group\s*\([^)]*"[a-z_]+\.[a-z_]+"'),
        "permission string literal in registry.add_group() — use a PERM_* constant",
    ),
    (
        re.compile(r'inertia\.render\s*\(\s*"[A-Z][A-Za-z]+/[A-Za-z/]+"'),
        "Inertia page identifier literal in render() — use a _PAGE_* constant",
    ),
    (
        re.compile(r'depends_on\s*=\s*\[[^\]]*"[A-Z][A-Za-z]+"'),
        "module name literal in depends_on — use a _MODULE_* constant",
    ),
]

# Files whose path contains any of these substrings are skipped entirely.
_SKIP_PATH_PARTS = ("tests/", "test_", "/constants.py", "scripts/")


def _should_skip(path: Path, root: Path) -> bool:
    rel = path.as_posix()
    return any(part in rel for part in _SKIP_PATH_PARTS)


def _docstring_lines(source: str) -> set[int]:
    """Return line numbers that are module/class/function docstrings.

    The earlier implementation flagged *every* line that contained a string
    token, which silently disabled the rules: a real ``RequiresPermission(
    "users.manage")`` call always has a string on the same line as the
    function name, so the line was excluded. We only want to skip docstring
    bodies — strings that sit on their own as the first statement of a
    module, class, or function.
    """
    inside: set[int] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return inside

    def _maybe_record(node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if not body:
            return
        first = body[0]
        if not isinstance(first, ast.Expr):
            return
        value = first.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            end = getattr(first, "end_lineno", first.lineno)
            inside.update(range(first.lineno, end + 1))

    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            _maybe_record(node)
    return inside


def _check_file(path: Path) -> list[tuple[int, str, str]]:
    """Return a list of (line_number, line, message) violations."""
    violations: list[tuple[int, str, str]] = []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return violations
    docstring_lines = _docstring_lines(source)
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or lineno in docstring_lines:
            continue
        for pattern, message in _RULES:
            if pattern.search(line):
                violations.append((lineno, line.rstrip(), message))
                break
    return violations


def _list_git_tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [root / line for line in result.stdout.splitlines() if line.endswith(".py")]


def _walk_filesystem(root: Path) -> list[Path]:
    return list(root.rglob("*.py"))


def _collect_candidates(root: Path, use_git: bool) -> list[Path]:
    return _list_git_tracked_files(root) if use_git else _walk_filesystem(root)


def find_violations(
    paths: Iterable[Path],
    root: Path,
) -> list[tuple[Path, int, str, str]]:
    """Return (path, lineno, line, message) for every violation."""
    results: list[tuple[Path, int, str, str]] = []
    for path in paths:
        if _should_skip(path, root):
            continue
        for lineno, line, message in _check_file(path):
            results.append((path, lineno, line, message))
    return results


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    description = (__doc__ or "").splitlines()[0]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repo root to scan (default: cwd)",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="walk the filesystem instead of using git ls-files",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root: Path = args.root
    candidates = _collect_candidates(root, use_git=not args.no_git)
    violations = find_violations(candidates, root)
    if not violations:
        print("OK: no hardcoded magic strings found.")
        return 0

    print(f"FAIL: {len(violations)} hardcoded magic string(s) found:\n")
    for path, lineno, line, message in violations:
        rel = path.relative_to(root) if path.is_absolute() else path
        print(f"  {rel.as_posix()}:{lineno}: {message}")
        print(f"    {line}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
