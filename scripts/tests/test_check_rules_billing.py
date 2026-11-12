"""CLAUDE.md's rule that billing never commits bare (#340)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_rules


def _repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "root"\nversion = "0.0.11"\n', encoding="utf-8"
    )
    return tmp_path


def _errors(root: Path) -> str:
    return "\n".join(check_rules.check(root))


def _billing(root: Path, name: str, source: str) -> None:
    f = root / "modules" / "billing" / "sm_billing" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(source, encoding="utf-8")


def test_billing_bare_commit_fails(tmp_path):
    root = _repo(tmp_path)
    _billing(root, "a.py", "async def f(session):\n    await session.commit()\n")
    out = _errors(root)
    assert "modules/billing/sm_billing/a.py:2" in out
    assert "finalize_session" in out


def test_billing_commit_on_any_receiver_fails(tmp_path):
    root = _repo(tmp_path)
    _billing(root, "sub/b.py", "async def f(db):\n    await db.commit()\n")
    assert "sub/b.py:2" in _errors(root)


def test_billing_finalize_comment_and_string_pass(tmp_path):
    root = _repo(tmp_path)
    _billing(
        root,
        "a.py",
        "from simple_module_db import finalize_session\n"
        "# never commit() here\n"
        'DOC = "a bare commit() drops it"\n'
        "async def f(session):\n    await finalize_session(session)\n",
    )
    assert check_rules.check_billing_commits(root) == []


def test_billing_commit_allowlist_needs_a_listed_path(tmp_path):
    root = _repo(tmp_path)
    _billing(root, "a.py", "async def f(s):\n    await s.commit()\n")
    rel = "modules/billing/sm_billing/a.py"
    assert check_rules.check_billing_commits(root, {rel: "reason"}) == []
    assert check_rules.check_billing_commits(root, {"other.py": "reason"}) != []


def test_billing_commit_in_other_modules_is_not_checked(tmp_path):
    root = _repo(tmp_path)
    f = root / "modules" / "news" / "sm_news" / "a.py"
    f.parent.mkdir(parents=True)
    f.write_text("async def f(s):\n    await s.commit()\n", encoding="utf-8")
    assert check_rules.check_billing_commits(root) == []
