"""records type public submissions

Revision ID: d6c76536d36d
Revises: 66e901950f68
Create Date: 2026-10-24 14:43:05.163109

``records_type.public_submissions`` (#101): whether, and how, a record type
accepts submissions from the website — a contact form or a newsletter list.
Nullable JSON with no backfill: null means "not a submissions type", so every
existing type is unchanged and the feature is inert until one opts in. The
system fields such a type carries live in its ``fields`` JSON and the existing
index tables, so no record table changes.

Downgrading drops the column, which forgets which types accepted submissions;
their ``sm_*`` fields stay behind as ordinary stored definitions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d6c76536d36d"
down_revision: str | None = "66e901950f68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("records_type", sa.Column("public_submissions", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("records_type", "public_submissions")
