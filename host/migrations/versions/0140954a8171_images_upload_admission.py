"""images: the per-tenant upload admission lock

Revision ID: 0140954a8171
Revises: 466b55136e19
Create Date: 2026-10-29 14:52:23.262031

``images_upload_admission``: one row per tenant, written (row lock on
Postgres, write lock on SQLite) by every direct or ZIP upload open before it
counts the tenant's open uploads, so ``max_open_uploads_per_tenant`` cannot be
overshot by concurrent opens. Not tenant-scoped: ``tenant`` is the key.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0140954a8171"
down_revision: str | None = "466b55136e19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "images_upload_admission",
        sa.Column("tenant", sa.String(length=255), nullable=False),
        sa.Column("admitted", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant", name=op.f("pk_images_upload_admission")),
    )


def downgrade() -> None:
    op.drop_table("images_upload_admission")
