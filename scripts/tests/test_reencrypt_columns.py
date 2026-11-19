"""``reencrypt_secrets.py`` also rewrites a sealed *column* (events' subscription address).

The settings rows are in ``test_reencrypt_secrets.py``; this is the same all-or-nothing run
over ``reencrypt_support.COLUMN_TARGETS``: every tenant's rows, compare-and-set, values never
printed, a deleted row (empty column) left alone.
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reencrypt_support as rs
from test_reencrypt_secrets import (
    AI_KEY,
    NEW,
    OLD,
    _put,
    _reencrypt,
    _v1,
)


@pytest.fixture
def db(_migrated, tmp_path) -> Path:
    copy = tmp_path / "host.db"
    copy.write_bytes(_migrated.read_bytes())
    return copy


URL = "https://calendar.example/ical/private-TOKEN-1234/basic.ics"
TABLE, COLUMN = "events_subscription", "url_enc"


def _events(secret: str):
    module = rs.crypto_for("sm_events")
    assert module is not None
    module.set_secret_provider(lambda: secret)
    return module


def _row(value: str, tenant="t1", row_id="r1") -> rs.ColumnRow:
    return rs.ColumnRow("sm_events", TABLE, COLUMN, tenant, row_id, value)


def test_the_column_target_is_listed():
    assert rs.COLUMN_TARGETS == {"sm_events": ((TABLE, COLUMN),)}
    assert "sm_events" in rs.packages()


def test_column_rows_planned(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", OLD)
    sealed_old = _events(OLD).encrypt_value(URL)
    foreign = _events("a-key-nobody-lists").encrypt_value(URL)
    new = _events(NEW)
    try:
        assert rs.plan_column_row(_row(sealed_old)).outcome == rs.ROTATE
        assert rs.plan_column_row(_row(new.encrypt_value(URL))).outcome == rs.CURRENT
        assert rs.plan_column_row(_row("")).outcome == rs.EMPTY  # a deleted row
        assert rs.plan_column_row(_row("enc:v9:zzz")).outcome == rs.UNREADABLE
        assert rs.plan_column_row(_row(foreign)).outcome == rs.UNREADABLE  # no key opens it
        assert rs.plan_column_row(_row(_v1(URL, NEW))).outcome == rs.UPGRADE
        assert rs.plan_column_row(_row(URL)).outcome == rs.SEAL
        assert rs.plan_column_row(_row(URL), seal_plaintext=False).outcome == rs.PLAINTEXT_KEPT
        plan = rs.plan_column_row(_row(sealed_old), seal_plaintext=True)
        assert plan.new_value is not None
        assert new.decrypt_value(plan.new_value, "url") == URL
        assert URL not in plan.row.where()
        assert "TOKEN" not in plan.row.where()
    finally:
        _events(NEW)


def test_where_names_the_row_never_the_value():
    row = _row("enc:v2:secretish", tenant="acme", row_id="abc")
    assert row.where() == "events_subscription.url_enc (tenant acme, id abc)"


def _insert(db: Path, value: str, tenant="t1", deleted=False) -> str:
    row_id = uuid.uuid4().hex
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO events_subscription (tenant_id, is_deleted, id, calendar_id, created_by,"
            " url_enc, url_display, label, public, status, consecutive_failures, generation,"
            " item_count, last_counts, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'o', ?, 'https://calendar.example/…', 'L', 0, 'ok', 0, 0, 0,"
            " '{}', '2026-01-01 00:00:00', '2026-01-01 00:00:00')",
            (tenant, int(deleted), row_id, uuid.uuid4().hex, value),
        )
    return row_id


def _column(db: Path, row_id: str) -> str:
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT {COLUMN} FROM {TABLE} WHERE id = ?", (row_id,)).fetchone()[0]


def test_a_run_rotates_every_tenants_rows_and_prints_no_value(db, tmp_path):
    old = _events(OLD)
    a = _insert(db, old.encrypt_value(URL), tenant="t1")
    b = _insert(db, old.encrypt_value(URL + "b"), tenant="t2")
    gone = _insert(db, "", tenant="t1", deleted=True)
    current = _events(NEW).encrypt_value(URL + "c")
    c = _insert(db, current, tenant="t2")
    dry = _reencrypt(db, tmp_path, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert f"events_subscription.url_enc (tenant t1, id {a})" in dry.stdout
    assert f"events_subscription.url_enc (tenant t2, id {b})" in dry.stdout
    assert "TOKEN" not in dry.stdout + dry.stderr
    assert "enc:v2" not in dry.stdout + dry.stderr
    assert _events(OLD).decrypt_value(_column(db, a), "url") == URL  # nothing written yet
    result = _reencrypt(db, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "TOKEN" not in result.stdout + result.stderr
    new = _events(NEW)
    assert new.decrypt_value(_column(db, a), "url") == URL
    assert new.decrypt_value(_column(db, b), "url") == URL + "b"
    assert _column(db, c) == current  # already current: untouched
    assert _column(db, gone) == ""  # a deleted row holds nothing and gets nothing
    again = _reencrypt(db, tmp_path)
    assert again.returncode == 0
    assert "Nothing to re-encrypt" in again.stdout


def test_one_unreadable_column_row_writes_nothing_anywhere(db, tmp_path):
    old = _events(OLD)
    good = _insert(db, old.encrypt_value(URL))
    bad = _insert(db, _events("lost-key").encrypt_value(URL))
    _put(db, AI_KEY, _events(OLD).encrypt_value("not-ai"))  # an unreadable settings row too
    before = (_column(db, good), _column(db, bad))
    result = _reencrypt(db, tmp_path)
    assert result.returncode == 1
    assert "nothing was written" in result.stderr
    assert f"id {bad}" in result.stdout
    assert (_column(db, good), _column(db, bad)) == before


def test_plaintext_column_is_sealed_unless_told_not_to(db, tmp_path):
    keep = _insert(db, URL)
    result = _reencrypt(db, tmp_path, "--no-seal-plaintext")
    assert result.returncode == 0, result.stderr
    assert _column(db, keep) == URL
    sealed = _reencrypt(db, tmp_path)
    assert sealed.returncode == 0, sealed.stderr
    assert _column(db, keep).startswith("enc:v2:")
    assert _events(NEW).decrypt_value(_column(db, keep), "url") == URL


def test_a_missing_events_table_is_not_an_error(db, tmp_path):
    """A database migrated before events existed has no such table."""
    with sqlite3.connect(db) as conn:
        conn.execute(f"DROP TABLE {TABLE}")
    result = _reencrypt(db, tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.fixture(autouse=True)
def _restore_provider():
    yield
    rs.install_secret(NEW)
