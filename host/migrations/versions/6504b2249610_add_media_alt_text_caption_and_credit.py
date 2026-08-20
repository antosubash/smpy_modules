"""add media alt text, caption and credit

Revision ID: 6504b2249610
Revises: 7327cb99fe0a
Create Date: 2026-08-19 18:05:00.000000

Hand-adjusted from autogenerate: all three columns are NOT NULL, so each needs a
``server_default`` for the backfill — without one the ALTER has no value to
write into the assets already in the library and the migration aborts. The
defaults are dropped again afterwards so the application, not the database, owns
them from here on.

Empty string rather than NULL is the right blank here: "no alt text yet" and
"alt text deliberately empty" are the same state for an asset nobody has
described, and a nullable column would make every reader handle both.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6504b2249610"
down_revision: str | None = "7327cb99fe0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "pagebuilder_media"
_COLUMNS = (("alt_text", 500), ("caption", 500), ("credit", 200))


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        for name, length in _COLUMNS:
            batch.add_column(
                sa.Column(name, sa.String(length=length), nullable=False, server_default="")
            )

    with op.batch_alter_table(_TABLE) as batch:
        for name, _ in _COLUMNS:
            batch.alter_column(name, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        for name, _ in reversed(_COLUMNS):
            batch.drop_column(name)
