"""records type show_in_menu: per-type admin sidebar entry

Revision ID: b81c5f3a27d6
Revises: c4a17b9de0f2
Create Date: 2026-09-20 17:05:00.000000

``records_type.show_in_menu`` opts one type into its own entry in the admin
sidebar, next to the module's "Records" hub entry. Purely a navigation flag: it
changes no record, no index and no ``schema_version``.

**NOT NULL with ``server_default=false()``, deliberately.** The column has to
have a value for every row that already exists, and "off" is the only answer
that keeps an upgraded install looking exactly as it did — the sidebar gains
nothing until somebody turns a type on. The server default is what lets SQLite
add the column in place (``ALTER TABLE ... ADD COLUMN`` needs a non-null
default) and what keeps an ``INSERT`` written against the old shape legal on
Postgres; the model carries the same default on the Python side, so the two
cannot disagree.

Downgrading drops the column, which loses only which types were shown.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b81c5f3a27d6'
down_revision: str | None = 'c4a17b9de0f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'records_type',
        sa.Column('show_in_menu', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('records_type', 'show_in_menu')
