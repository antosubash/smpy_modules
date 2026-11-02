"""images: a pipeline restart records its starter

Revision ID: 466b55136e19
Revises: 4956d13dbf09
Create Date: 2026-10-29 14:30:11.896964

``images_pipeline_restart.run_as`` / ``access_basis``: who started a
whole-collection restart and whether as owner or manager, so the runner can
re-check that right before each chunk. Nullable: a restart recorded before
this is not checked.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "466b55136e19"
down_revision: str | None = "4956d13dbf09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "images_pipeline_restart", sa.Column("run_as", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "images_pipeline_restart", sa.Column("access_basis", sa.String(length=10), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("images_pipeline_restart", "access_basis")
    op.drop_column("images_pipeline_restart", "run_as")
