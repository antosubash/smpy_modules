"""Copied helpers stay copies (#127).

The families and their allowed differences are in ``parity_families.py``. This
file runs them, checks the comparison itself can see drift, and holds the few
copies that need more than a source comparison.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from parity_families import FAMILIES, NEWS, PB
from parity_support import REPO, Copy, Family, problems


@pytest.mark.parametrize("family", FAMILIES, ids=[f.name for f in FAMILIES])
def test_copies_have_not_drifted(family: Family) -> None:
    found = problems(family)
    assert not found, f"{family.name}:\n\n" + "\n\n".join(found)


def test_use_pending_dialog_is_byte_identical() -> None:
    """Nothing in it is module-specific, so there is nothing to mask."""
    news = (REPO / NEWS / "hooks/usePendingDialog.ts").read_bytes()
    pagebuilder = (REPO / PB / "hooks/usePendingDialog.ts").read_bytes()
    assert news == pagebuilder


def _literal(path: str, name: str) -> object:
    for node in ast.parse((REPO / path).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == name:
            return ast.literal_eval(node.value)  # type: ignore[arg-type]
    raise AssertionError(f"{name} not found in {path}")


def test_per_viewer_vary_names_the_same_headers() -> None:
    """Spelled as a string in one and a tuple in the other, so compared by value."""
    pagebuilder = _literal(f"{PB}/public_cache.py", "VARY")
    news = _literal(f"{NEWS}/endpoints/public/_urls.py", "PER_VIEWER_VARY")
    assert pagebuilder == ", ".join(news)  # type: ignore[arg-type]


def test_slug_bound_is_one_number() -> None:
    """Both TypeScript copies cut at the column's length, which the fixture states."""
    fixture = json.loads((REPO / "tests/fixtures/slug_cases.json").read_text(encoding="utf-8"))
    assert _literal(f"{NEWS}/constants.py", "MAX_SLUG_LEN") == fixture["max_length"]
    for path in (f"{NEWS}/utils/slugify.ts", f"{PB}/utils/slugify.ts"):
        source = (REPO / path).read_text(encoding="utf-8")
        assert f"const MAX_SLUG_LEN = {fixture['max_length']};" in source, path


# --- the comparison itself -----------------------------------------------------


def _family(
    tmp_path: Path, first: str, second: str, suffix: str = ".py", renames=({}, {}), **kwargs
) -> Family:
    copies = []
    for name, source, rename in zip("ab", (first, second), renames, strict=True):
        (tmp_path / f"{name}{suffix}").write_text(source, encoding="utf-8")
        copies.append(Copy(str(tmp_path / f"{name}{suffix}"), rename))
    return Family("probe", tuple(copies), **kwargs)


def test_comments_and_docstrings_are_not_drift(tmp_path: Path) -> None:
    a = 'def f(x):\n    """About a."""\n    # a\n    return x + 1\n'
    b = 'def f(x):\n    """About b, at length."""\n    return x + 1  # b\n'
    assert problems(_family(tmp_path, a, b)) == []


def test_a_changed_body_is_drift(tmp_path: Path) -> None:
    found = problems(_family(tmp_path, "def f(x):\n    return x\n", "def f(x):\n    return -x\n"))
    assert len(found) == 1 and "'f' has drifted" in found[0]


def test_a_declaration_in_one_copy_only_is_drift(tmp_path: Path) -> None:
    found = problems(_family(tmp_path, "def f(): pass\n", "def f(): pass\ndef g(): pass\n"))
    assert found == ["'g' is missing from " + str(tmp_path / "a.py")]


def test_renames_mask_module_names(tmp_path: Path) -> None:
    family = _family(
        tmp_path,
        "def f(s: NewsSettings): return s\n",
        "def f(s: PageSettings): return s\n",
        renames=({"NewsSettings": "S"}, {"PageSettings": "S"}),
    )
    assert problems(family) == []


def test_an_allowance_nobody_needs_any_more_fails(tmp_path: Path) -> None:
    family = _family(tmp_path, "def f(): pass\n", "def f(): pass\n", differ={"f": "was different"})
    assert problems(family) == ["'f' is allowed to differ, but every copy now agrees"]


def test_typescript_formatting_is_not_drift(tmp_path: Path) -> None:
    a = "/** a */\nexport function f(a: string, b: string): string {\n  return a + b; // sum\n}\n"
    b = "export function f(\n  a: string,\n  b: string,\n): string {\n  return a + b;\n}\n"
    assert problems(_family(tmp_path, a, b, suffix=".ts")) == []


def test_a_typescript_change_is_drift(tmp_path: Path) -> None:
    a = "export const X = /^a$/;\n"
    b = "export const X = /^b$/;\n"
    assert len(problems(_family(tmp_path, a, b, suffix=".ts"))) == 1
