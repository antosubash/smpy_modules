"""Every ``.commit()`` in ``sm_billing`` is one we know is safe (#121).

Billing must end a session that may change a tenant's status with
``simple_module_db.finalize_session``: ``TenantStatusChanged`` and the
membership-cache invalidation ride on ``on_commit``, which a bare ``commit()``
drops. The behavioural tests (``status_events``) catch a swap on the paths
they drive; this catches a new ``commit()`` anywhere else.

Sites are matched by file and qualified scope (``Class.method``,
``outer.inner``), not line, so editing around them does not break the test.
Adding one means arguing here why it never touches a tenant's status.
"""

from __future__ import annotations

import ast
from pathlib import Path

import sm_billing

PACKAGE = Path(sm_billing.__file__).parent

#: (path under sm_billing, qualified scope) → why a plain commit is fine.
ALLOWED = {
    ("webhooks.py", "_claim"): "inserts the dedup row only",
    ("webhooks.py", "_finish"): "records the event outcome only",
    ("seats.py", "push_quantity"): "writes Subscription.quantity only",
    ("plans.py", "seed_default_plan"): "startup seed of the free plan",
}


class _Scopes(ast.NodeVisitor):
    """Each ``.commit`` attribute, by the qualified name of the scope it is in.

    Every scope is walked, class bodies included, and a nested function is
    ``outer.inner``, so an allowed name cannot cover a different function.
    """

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.found: set[str] = set()

    def _scope(self, node: ast.AST, name: str) -> None:
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815 - ast API
    visit_ClassDef = visit_FunctionDef  # noqa: N815 - ast API

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "commit":
            self.found.add(".".join(self.stack) or "<module>")
        self.generic_visit(node)


def _sites_in(source: str, rel: str) -> set[tuple[str, str]]:
    scopes = _Scopes()
    scopes.visit(ast.parse(source, filename=rel))
    return {(rel, name) for name in scopes.found}


def _commit_sites() -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        sites |= _sites_in(path.read_text(encoding="utf-8"), rel)
    return sites


def test_scanner_sees_class_bodies_and_qualifies_nested_functions():
    source = """
class Repo:
    async def save(self, s):
        await s.commit()
    hook = staticmethod(lambda s: s.commit())

async def _claim(s):
    async def _claim(t):
        await t.commit()
"""
    assert _sites_in(source, "x.py") == {
        ("x.py", "Repo.save"),
        ("x.py", "Repo"),
        ("x.py", "_claim._claim"),
    }


def test_no_commit_outside_the_allowlist():
    unexpected = _commit_sites() - ALLOWED.keys()
    assert not unexpected, (
        f"bare .commit() in {sorted(unexpected)}: use simple_module_db.finalize_session "
        "(or add the site to ALLOWED with the reason it never changes a tenant's status)"
    )


def test_allowlist_has_no_stale_entries():
    stale = ALLOWED.keys() - _commit_sites()
    assert not stale, f"no .commit() left in {sorted(stale)}; drop them from ALLOWED"
