"""Every ``.commit()`` in ``sm_billing`` is one we know is safe (#121).

Billing must end a session that may change a tenant's status with
``simple_module_db.finalize_session``: ``TenantStatusChanged`` and the
membership-cache invalidation ride on ``on_commit``, which a bare ``commit()``
drops. The behavioural tests (``status_events``) catch a swap on the paths
they drive; this catches a new ``commit()`` anywhere else.

Sites are matched by file and enclosing function, not line, so editing around
them does not break the test. Adding one means arguing here why it never
touches a tenant's status.
"""

from __future__ import annotations

import ast
from pathlib import Path

import sm_billing

PACKAGE = Path(sm_billing.__file__).parent

#: (path under sm_billing, enclosing function) → why a plain commit is fine.
ALLOWED = {
    ("webhooks.py", "_claim"): "inserts the dedup row only",
    ("webhooks.py", "_finish"): "records the event outcome only",
    ("seats.py", "push_quantity"): "writes Subscription.quantity only",
    ("plans.py", "seed_default_plan"): "startup seed of the free plan",
}


def _commit_sites() -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Attribute) and node.attr == "commit":
                    sites.add((rel, func.name))
        # A commit at module or class level has no enclosing function.
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute) and sub.attr == "commit":
                        sites.add((rel, "<module>"))
    return sites


def test_no_commit_outside_the_allowlist():
    unexpected = _commit_sites() - ALLOWED.keys()
    assert not unexpected, (
        f"bare .commit() in {sorted(unexpected)}: use simple_module_db.finalize_session "
        "(or add the site to ALLOWED with the reason it never changes a tenant's status)"
    )


def test_allowlist_has_no_stale_entries():
    stale = ALLOWED.keys() - _commit_sites()
    assert not stale, f"no .commit() left in {sorted(stale)}; drop them from ALLOWED"
