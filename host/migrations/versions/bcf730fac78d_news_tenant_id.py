"""news: tenant_id on every news table

Revision ID: bcf730fac78d
Revises: c493630090f0
Create Date: 2026-10-08 12:00:00.000000

News adopts the framework's ``MultiTenantMixin``, as pagebuilder did in
``c493630090f0``. All six tables get ``tenant_id VARCHAR(50) NOT NULL`` plus
the mixin's ``ix_<table>_tenant_id``, and every natural key becomes per
tenant:

* ``news_articles (locale, slug)`` and ``(translation_group, locale)``,
* ``news_article_redirects (locale, from_slug)``,
* ``news_categories (name)`` and ``(slug)``,
* ``news_tags (name)`` and ``(slug)``,

each gain ``tenant_id`` as their leading column. The category and tag keys
were global unique indexes named ``ix_<table>_<column>``; the models keep a
plain ``index=True`` on those columns, so the same names come back
non-unique and the per-tenant keys take ``uq_<table>_tenant_<column>``.

**Order.** The old uniques are dropped first, then each table gets the column
nullable, is backfilled with ``'default'``, and is altered ``NOT NULL`` — no
server default is left behind, so a statement that forgets the tenant is a
``NOT NULL`` failure rather than a row silently filed under ``default``. The
new uniques are created last, on populated columns. ``DEFAULT`` repeats
``news.tenancy.DEFAULT_TENANT`` on purpose: a revision must not change meaning
if the constant ever moves.

**SQLite** cannot alter a column's nullability in place, so that step runs in
``batch_alter_table``, which rebuilds the table there (and is a plain
``ALTER`` on Postgres). No news index is partial, so nothing is lost in the
rebuild's reflection.

**Downgrading is lossy, and refusable.** It restores the global uniques, so it
is refused, before any DDL, once two tenants share an article slug, a
translation link, a redirect, or a category or tag name or slug; where it
succeeds it merges every tenant's rows into one install. Only a single-tenant
database round-trips.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bcf730fac78d"
down_revision: str | None = "c493630090f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT = "default"
COLUMN = "tenant_id"

ARTICLES = "news_articles"
REDIRECTS = "news_article_redirects"
CATEGORIES = "news_categories"
TAGS = "news_tags"

TABLES = (
    ARTICLES,
    "news_article_revisions",
    REDIRECTS,
    CATEGORIES,
    TAGS,
    "news_article_tags",
)

# (table, old name, old columns, new name, new columns).
KEYS = (
    (
        ARTICLES,
        "ix_news_articles_locale_slug",
        ["locale", "slug"],
        "ix_news_articles_tenant_locale_slug",
        [COLUMN, "locale", "slug"],
    ),
    (
        ARTICLES,
        "ix_news_articles_group_locale",
        ["translation_group", "locale"],
        "ix_news_articles_tenant_group_locale",
        [COLUMN, "translation_group", "locale"],
    ),
    (
        REDIRECTS,
        "ix_news_article_redirects_locale_from_slug",
        ["locale", "from_slug"],
        "ix_news_article_redirects_tenant_locale_from_slug",
        [COLUMN, "locale", "from_slug"],
    ),
    (CATEGORIES, "ix_news_categories_name", ["name"], "uq_news_categories_tenant_name", [COLUMN, "name"]),
    (CATEGORIES, "ix_news_categories_slug", ["slug"], "uq_news_categories_tenant_slug", [COLUMN, "slug"]),
    (TAGS, "ix_news_tags_name", ["name"], "uq_news_tags_tenant_name", [COLUMN, "name"]),
    (TAGS, "ix_news_tags_slug", ["slug"], "uq_news_tags_tenant_slug", [COLUMN, "slug"]),
)

# Old unique indexes whose name the models keep as a plain, non-unique index.
_KEPT_PLAIN = {(table, old) for table, old, _, _, _ in KEYS if table in (CATEGORIES, TAGS)}


def upgrade() -> None:
    for table, old, _, _, _ in KEYS:
        op.drop_index(old, table_name=table)
    for table in TABLES:
        op.add_column(table, sa.Column(COLUMN, sa.String(50), nullable=True))
        op.execute(
            sa.text(f"UPDATE {table} SET {COLUMN} = :tenant").bindparams(tenant=DEFAULT)
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column(COLUMN, existing_type=sa.String(50), nullable=False)
        op.create_index(f"ix_{table}_{COLUMN}", table, [COLUMN])
    for table, old, columns, new, new_columns in KEYS:
        op.create_index(new, table, new_columns, unique=True)
        if (table, old) in _KEPT_PLAIN:
            op.create_index(old, table, columns, unique=False)


def _shared_keys(bind) -> list[str]:
    """Every old key value more than one tenant holds — the rows the restored
    global uniques could not take."""
    found = []
    for table, _, columns, _, _ in KEYS:
        cols = ", ".join(columns)
        rows = bind.execute(
            sa.text(
                f"SELECT {cols} FROM {table} GROUP BY {cols} "
                f"HAVING count(*) > 1 ORDER BY {cols} LIMIT 20"
            )
        ).all()
        found += [f"{table}({cols})={tuple(row)!r}" for row in rows]
    return found


def downgrade() -> None:
    bind = op.get_bind()
    # Before any DDL: SQLite's DDL is not transactional, so a unique failing
    # half way would strand the schema between revisions.
    if not op.get_context().as_sql:
        shared = _shared_keys(bind)
        if shared:
            raise RuntimeError(
                "news: refusing to downgrade bcf730fac78d — the global uniques it "
                "restores cannot hold while tenants share these (first 20 per key): "
                + "; ".join(shared)
                + ". Rename or delete the duplicates in all but one tenant, then retry. "
                "Nothing was changed."
            )
    for table, old, _, new, _ in KEYS:
        op.drop_index(new, table_name=table)
        if (table, old) in _KEPT_PLAIN:
            op.drop_index(old, table_name=table)
    for table in TABLES:
        op.drop_index(f"ix_{table}_{COLUMN}", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column(COLUMN)
    for table, old, columns, _, _ in KEYS:
        op.create_index(old, table, columns, unique=True)
