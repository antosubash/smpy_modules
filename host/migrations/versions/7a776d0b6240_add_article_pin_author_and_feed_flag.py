"""add article pin, author and feed flag

Revision ID: 7a776d0b6240
Revises: 0cce3a443a27
Create Date: 2026-08-19 16:45:00.000000

Hand-adjusted from autogenerate: all three columns are NOT NULL, so each needs a
``server_default`` for the backfill — without one the ALTER has no value to
write into existing rows and the migration aborts on any database that already
holds articles. The defaults are dropped again afterwards so the application,
not the database, owns them from here on.

``show_in_feed`` backfills to true on purpose: every article that existed before
this column was in the feed, and defaulting it to false would silently empty
every feed block on deploy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a776d0b6240"
down_revision: str | None = "0cce3a443a27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "news_articles"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column(
                "show_in_feed", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
        batch.add_column(
            sa.Column(
                "author", sa.String(length=120), nullable=False, server_default=""
            )
        )

    op.create_index(op.f("ix_news_articles_pinned"), _TABLE, ["pinned"], unique=False)
    op.create_index(
        op.f("ix_news_articles_show_in_feed"), _TABLE, ["show_in_feed"], unique=False
    )

    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column("pinned", server_default=None)
        batch.alter_column("show_in_feed", server_default=None)
        batch.alter_column("author", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_news_articles_show_in_feed"), table_name=_TABLE)
    op.drop_index(op.f("ix_news_articles_pinned"), table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("author")
        batch.drop_column("show_in_feed")
        batch.drop_column("pinned")
