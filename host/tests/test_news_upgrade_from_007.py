"""Upgrading a 0.0.7 host keeps every article's language and translation links.

On 0.0.7 a news article was a sidecar over a pagebuilder page, and it was
multilingual *through* that page: the page's ``locale`` and
``translation_group`` were the article's. ``7a1a2e92f6df`` moves the content
onto the article and drops ``page_id``; ``d4e7c1a9b602`` then gives the article
a language of its own. Unless the first sets the page's language aside for the
second, every article lands in the default language and loses its translations
— and two languages sharing a slug abort the upgrade outright on a slug-only
unique index.

Real alembic against a real file, because the bug lives in the order the
revisions run in and in what each can still see, which nothing short of the
migration chain reproduces.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# The news chain just before the article took its content over, and the
# revision that made pages multilingual — together, what a 0.0.7 host has run.
BEFORE_OWNERSHIP = "6504b2249610"
PAGES_MULTILINGUAL = "b1f4a72c9d30"

SEED = """
INSERT INTO pagebuilder_pages (id, slug, title, status, draft_data, published_data,
  index_in_search, is_template, show_in_header_nav, show_in_footer, locale, translation_group)
VALUES
  (7, 'launch', 'Launch day', 'PUBLISHED', '{}', '{}', 1, 0, 0, 0, 'en', 'grp-launch'),
  (8, 'launch', 'Starttag', 'PUBLISHED', '{}', '{}', 1, 0, 0, 0, 'de', 'grp-launch');
INSERT INTO pagebuilder_page_redirects (from_slug, page_id, locale)
VALUES ('old-launch', 7, 'en'), ('old-launch', 8, 'de');
INSERT INTO news_articles (id, page_id, category, pinned, show_in_feed, author)
VALUES (1, 7, 'general', 0, 1, 'A'), (2, 8, 'general', 0, 1, 'B'), (3, 99, 'general', 0, 1, 'C');
"""


def _alembic(db: Path, *args: str) -> None:
    env = {**os.environ, "SM_DATABASE_URL": f"sqlite+aiosqlite:///{db}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.fixture(scope="module")
def upgraded(tmp_path_factory) -> sqlite3.Connection:
    db = tmp_path_factory.mktemp("upgrade") / "host.db"
    _alembic(db, "upgrade", BEFORE_OWNERSHIP)
    _alembic(db, "upgrade", PAGES_MULTILINGUAL)
    con = sqlite3.connect(db)
    con.executescript(SEED)
    con.commit()
    _alembic(db, "upgrade", "heads")
    yield con
    con.close()


def test_each_article_keeps_its_language_and_translation_group(upgraded) -> None:
    rows = upgraded.execute(
        "SELECT id, slug, locale, translation_group FROM news_articles ORDER BY id"
    ).fetchall()
    assert rows[:2] == [
        (1, "launch", "en", "grp-launch"),
        (2, "launch", "de", "grp-launch"),
    ]


def test_an_orphaned_article_falls_back_to_the_default_language(upgraded) -> None:
    article_id, locale, group = upgraded.execute(
        "SELECT id, locale, translation_group FROM news_articles WHERE id = 3"
    ).fetchone()
    assert (article_id, locale) == (3, "en")
    assert group and group != "grp-launch"


def test_redirects_keep_their_language(upgraded) -> None:
    rows = upgraded.execute(
        "SELECT from_slug, article_id, locale FROM news_article_redirects ORDER BY article_id"
    ).fetchall()
    assert rows == [("old-launch", 1, "en"), ("old-launch", 2, "de")]


def test_nothing_is_left_behind(upgraded) -> None:
    carry = upgraded.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'news_article_%carry'"
    ).fetchall()
    assert carry == []
