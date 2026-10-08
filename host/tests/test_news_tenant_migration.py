"""News's tenant_id revision: backfill, per-tenant keys, a refusable downgrade.

News adopts ``MultiTenantMixin`` the way pagebuilder did in ``c493630090f0``:
every news table gains ``tenant_id``, existing rows are filed under
``default``, and every natural key (article slug, translation link, redirect,
category and tag name/slug) becomes unique per tenant. Downgrading restores
the global keys, so it must refuse — before any DDL — while two tenants share
one, and succeed once they don't.

Real alembic against a real file, as in ``test_news_upgrade_from_007``: the
behaviour lives in the revision chain, which nothing short of running it
reproduces. The last test runs ``alembic check`` so the revision and the
models cannot drift apart.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# The main-line head before news became tenant-aware.
BEFORE = "c493630090f0"

TABLES = (
    "news_articles",
    "news_article_revisions",
    "news_article_redirects",
    "news_categories",
    "news_tags",
    "news_article_tags",
)

SEED = """
INSERT INTO news_categories (id, name, slug, position) VALUES (1, 'General', 'general', 0);
INSERT INTO news_tags (id, name, slug) VALUES (1, 'Launch', 'launch');
INSERT INTO news_articles (id, category, pinned, show_in_feed, author, slug, title,
  draft_data, status, index_in_search, locale, translation_group)
VALUES (1, 'general', 0, 1, 'A', 'hello', 'Hello', '{}', 'DRAFT', 1, 'en', 'grp-hello');
INSERT INTO news_article_redirects (id, from_slug, article_id, locale)
VALUES (1, 'old-hello', 1, 'en');
INSERT INTO news_article_revisions (id, article_id, title, data, event)
VALUES (1, 1, 'Hello', '{}', 'PUBLISH');
INSERT INTO news_article_tags (article_id, tag_id) VALUES (1, 1);
"""

# The same natural keys, filed under a second tenant.
SECOND_TENANT = """
INSERT INTO news_categories (id, name, slug, position, tenant_id)
VALUES (2, 'General', 'general', 0, 'b');
INSERT INTO news_articles (id, category, pinned, show_in_feed, author, slug, title,
  draft_data, status, index_in_search, locale, translation_group, tenant_id)
VALUES (2, 'general', 0, 1, 'B', 'hello', 'Hello', '{}', 'DRAFT', 1, 'en', 'grp-hello', 'b');
"""


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


def _query(db: Path, sql: str) -> list[tuple]:
    with contextlib.closing(sqlite3.connect(db)) as con:
        return con.execute(sql).fetchall()


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("news-tenant") / "host.db"
    _ok(path, "upgrade", BEFORE)
    _execute(path, SEED)
    _ok(path, "upgrade", "heads")
    return path


@pytest.mark.parametrize("table", TABLES)
def test_existing_rows_are_filed_under_the_default_tenant(db, table) -> None:
    assert _query(db, f"SELECT DISTINCT tenant_id FROM {table}") == [("default",)]


def test_tenant_id_is_not_null_without_a_server_default(db) -> None:
    for table in TABLES:
        column = next(c for c in _query(db, f"PRAGMA table_info({table})") if c[1] == "tenant_id")
        _, _, _, notnull, default, _ = column
        assert (notnull, default) == (1, None), table


def test_downgrade_is_refused_while_tenants_share_a_key_then_allowed(db) -> None:
    # A second tenant may reuse every natural key the first one holds.
    _execute(db, SECOND_TENANT)

    refused = _alembic(db, "downgrade", BEFORE)
    assert refused.returncode != 0
    assert "RuntimeError" in refused.stderr
    assert "refusing to downgrade" in refused.stderr
    # Nothing changed: the column is still there and both tenants' rows remain.
    assert _query(db, "SELECT count(*) FROM news_articles WHERE tenant_id = 'b'") == [(1,)]

    _execute(
        db,
        "DELETE FROM news_articles WHERE tenant_id = 'b';"
        "DELETE FROM news_categories WHERE tenant_id = 'b';",
    )
    _ok(db, "downgrade", BEFORE)
    columns = [c[1] for c in _query(db, "PRAGMA table_info(news_articles)")]
    assert "tenant_id" not in columns
    assert _query(db, "SELECT slug FROM news_articles") == [("hello",)]
    # And back up again, so the round trip is whole.
    _ok(db, "upgrade", "heads")


def test_the_models_match_the_migrated_schema(tmp_path) -> None:
    path = tmp_path / "check.db"
    _ok(path, "upgrade", "heads")
    result = _alembic(path, "check")
    assert result.returncode == 0, result.stderr[-4000:]
    assert "No new upgrade operations detected" in result.stdout + result.stderr
