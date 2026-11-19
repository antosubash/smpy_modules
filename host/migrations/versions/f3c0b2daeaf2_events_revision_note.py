"""events revision note

Adds the nullable ``events_revision.note`` (at most 1000 characters): a reject
note, or the list of overrides a series change dropped. Nothing else is altered;
no data migration. No branch label (``events`` is already named by
``b8e1d0783868``).

Revision ID: f3c0b2daeaf2
Revises: b8e1d0783868
Create Date: 2026-11-17 23:48:45.133086
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c0b2daeaf2"
down_revision: str | None = "b8e1d0783868"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("events_revision") as batch:
        batch.add_column(sa.Column("note", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events_revision") as batch:
        batch.drop_column("note")
