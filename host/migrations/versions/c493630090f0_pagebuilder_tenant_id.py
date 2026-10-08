"""pagebuilder: tenant_id on every pagebuilder table

Revision ID: c493630090f0
Revises: 52ce60faa542
Create Date: 2026-10-05 12:00:00.000000

Pagebuilder adopts the framework's ``MultiTenantMixin`` (#38,
``docs/superpowers/specs/2026-10-05-pagebuilder-tenancy-design.md``). All nine
tables get ``tenant_id VARCHAR(50) NOT NULL`` plus the mixin's
``ix_<table>_tenant_id``, and every natural key becomes per tenant:

* ``pagebuilder_pages (locale, slug)`` and ``(translation_group, locale)``,
* ``pagebuilder_page_redirects (locale, from_slug)``,
* ``pagebuilder_media (filename)`` — a global unique index until now,
* ``pagebuilder_pending_imports (status) WHERE status = 'PENDING'``,

each gain ``tenant_id`` as their leading column.

**Order.** The old uniques are dropped first, then each table gets the column
nullable, is backfilled with ``'default'``, and is altered ``NOT NULL`` — no
server default is left behind, so a statement that forgets the tenant is a
``NOT NULL`` failure rather than a row silently filed under ``default``. The
new uniques are created last, on populated columns. ``DEFAULT`` repeats
``pagebuilder.tenancy.DEFAULT_TENANT`` on purpose: a revision must not change
meaning if the constant ever moves.

**SQLite** cannot alter a column's nullability in place, so that step runs in
``batch_alter_table``, which rebuilds the table there (and is a plain
``ALTER`` on Postgres). The partial pending-import index is dropped before the
rebuild and recreated after, so its ``WHERE`` cannot be lost in reflection.

**Downgrading is lossy, and refusable.** It restores the global uniques, so it
is refused, before any DDL, once two tenants share a slug, a redirect, a media
filename or a pending import; where it succeeds it merges every tenant's rows
into one install. Only a single-tenant database round-trips.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c493630090f0"
down_revision: str | None = "52ce60faa542"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT = "default"
COLUMN = "tenant_id"

PAGES = "pagebuilder_pages"
REDIRECTS = "pagebuilder_page_redirects"
MEDIA = "pagebuilder_media"
PENDING = "pagebuilder_pending_imports"

TABLES = (
    PAGES,
    "pagebuilder_page_revisions",
    REDIRECTS,
    MEDIA,
    "pagebuilder_layout",
    "pagebuilder_layout_revisions",
    "pagebuilder_snapshots",
    "pagebuilder_snapshot_media",
    PENDING,
)

_ONE_PENDING = "uq_pagebuilder_pending_imports_one_pending"
_PENDING_WHERE = "status = 'PENDING'"

# (table, old name, old columns, new name, new columns); the pending-import
# partial index keeps its name, and is the only one with a WHERE.
KEYS = (
    (
        PAGES,
        "ix_pagebuilder_pages_locale_slug",
        ["locale", "slug"],
        "ix_pagebuilder_pages_tenant_locale_slug",
        [COLUMN, "locale", "slug"],
    ),
    (
        PAGES,
        "ix_pagebuilder_pages_group_locale",
        ["translation_group", "locale"],
        "ix_pagebuilder_pages_tenant_group_locale",
        [COLUMN, "translation_group", "locale"],
    ),
    (
        REDIRECTS,
        "ix_pagebuilder_page_redirects_locale_from_slug",
        ["locale", "from_slug"],
        "ix_pagebuilder_page_redirects_tenant_locale_from_slug",
        [COLUMN, "locale", "from_slug"],
    ),
    (
        MEDIA,
        "ix_pagebuilder_media_filename",
        ["filename"],
        "uq_pagebuilder_media_tenant_filename",
        [COLUMN, "filename"],
    ),
    (PENDING, _ONE_PENDING, ["status"], _ONE_PENDING, [COLUMN, "status"]),
)


def _create_unique(name: str, table: str, columns: list[str]) -> None:
    where = {}
    if name == _ONE_PENDING:
        where = {
            "sqlite_where": sa.text(_PENDING_WHERE),
            "postgresql_where": sa.text(_PENDING_WHERE),
        }
    op.create_index(name, table, columns, unique=True, **where)


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
    for table, _, _, new, columns in KEYS:
        _create_unique(new, table, columns)


def _shared_keys(bind) -> list[str]:
    """Every old key value more than one tenant holds — the rows the restored
    global uniques could not take. Pending imports count only while PENDING."""
    found = []
    for table, _, columns, _, _ in KEYS:
        cols = ", ".join(columns)
        where = f" WHERE {_PENDING_WHERE}" if table == PENDING else ""
        rows = bind.execute(
            sa.text(
                f"SELECT {cols} FROM {table}{where} GROUP BY {cols} "
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
                "pagebuilder: refusing to downgrade c493630090f0 — the global uniques it "
                "restores cannot hold while tenants share these (first 20 per key): "
                + "; ".join(shared)
                + ". Rename or delete the duplicates in all but one tenant, then retry. "
                "Nothing was changed."
            )
    for table, _, _, new, _ in KEYS:
        op.drop_index(new, table_name=table)
    for table in TABLES:
        op.drop_index(f"ix_{table}_{COLUMN}", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column(COLUMN)
    for table, old, columns, _, _ in KEYS:
        _create_unique(old, table, columns)
