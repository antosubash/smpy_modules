"""Pagebuilder's role rows: created by name on upgrade, removed only unassigned.

``register_permissions`` maps ``pagebuilder_editor``, ``pagebuilder_publisher``
and ``pagebuilder_approver`` to permissions, but the users admin can assign a
role only once a ``users_role`` row exists (#320). Revision ``541bfbe29a28``
inserts the missing ones, leaves a row a host created itself untouched, and on
downgrade keeps any role a user still holds.

Real alembic against a real file, as in ``test_news_tenant_migration``.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The role rows' revision and the one before it. Tests stop at ``REVISION`` rather
# than ``heads`` so a later revision cannot change what they exercise.
BEFORE = "4381e1c2ac7e"
REVISION = "541bfbe29a28"

# GUID() stores a UUID as its dashed string on SQLite.
EXPECTED = {
    "pagebuilder_editor": ("e2c8518c-4ef4-5eb2-bfd5-7a269cb30626", "PageBuilder: edit pages"),
    "pagebuilder_publisher": (
        "5e0cc30a-c719-5ca3-919a-55a512f27bea",
        "PageBuilder: edit and publish pages",
    ),
    "pagebuilder_approver": (
        "514a9fde-1566-5e5f-9584-c3bd5b4be548",
        "PageBuilder: edit, publish and approve pages",
    ),
}

OWN_EDITOR = (
    "INSERT INTO users_role (id, name, description) VALUES ('{id}', 'pagebuilder_editor', 'Ours');"
)


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SM_DATABASE_URL": f"sqlite+aiosqlite:///{db}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _ok(db: Path, *args: str) -> None:
    result = _alembic(db, *args)
    assert result.returncode == 0, result.stderr[-2000:]


def _execute(db: Path, script: str) -> None:
    with contextlib.closing(sqlite3.connect(db)) as con:
        con.executescript(script)
        con.commit()


def _roles(db: Path) -> dict[str, tuple[str, str]]:
    with contextlib.closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT name, id, description FROM users_role WHERE name LIKE 'pagebuilder_%'"
        ).fetchall()
    return {name: (id_, description) for name, id_, description in rows}


def test_upgrade_creates_the_three_roles(tmp_path) -> None:
    db = tmp_path / "host.db"
    _ok(db, "upgrade", BEFORE)
    assert _roles(db) == {}
    _ok(db, "upgrade", REVISION)
    assert _roles(db) == EXPECTED


def test_a_role_the_host_created_is_kept(tmp_path) -> None:
    db = tmp_path / "host.db"
    _ok(db, "upgrade", BEFORE)
    own_id = "00000000-0000-0000-0000-000000000009"
    _execute(db, OWN_EDITOR.format(id=own_id))
    _ok(db, "upgrade", REVISION)
    assert _roles(db) == {**EXPECTED, "pagebuilder_editor": (own_id, "Ours")}
    # Downgrade removes only the rows this revision created, by id.
    _ok(db, "downgrade", BEFORE)
    assert _roles(db) == {"pagebuilder_editor": (own_id, "Ours")}


def test_downgrade_keeps_an_assigned_role(tmp_path) -> None:
    db = tmp_path / "host.db"
    _ok(db, "upgrade", REVISION)
    publisher_id = EXPECTED["pagebuilder_publisher"][0]
    user_id = "11111111-1111-1111-1111-111111111111"
    _execute(
        db,
        "INSERT INTO users_user (id, email, hashed_password, is_active, is_superuser,"
        f" is_verified) VALUES ('{user_id}', 'a@example.org', 'x', 1, 0, 1);"
        "INSERT INTO users_user_role (user_id, role_id, assigned_at)"
        f" VALUES ('{user_id}', '{publisher_id}', CURRENT_TIMESTAMP);",
    )
    _ok(db, "downgrade", BEFORE)
    assert _roles(db) == {"pagebuilder_publisher": EXPECTED["pagebuilder_publisher"]}
    # Up again: the kept row is not duplicated, the other two come back.
    _ok(db, "upgrade", REVISION)
    assert _roles(db) == EXPECTED


def test_the_models_match_the_migrated_schema(tmp_path) -> None:
    db = tmp_path / "check.db"
    _ok(db, "upgrade", "heads")
    result = _alembic(db, "check")
    assert result.returncode == 0, result.stderr[-4000:]
    assert "No new upgrade operations detected" in result.stdout + result.stderr
