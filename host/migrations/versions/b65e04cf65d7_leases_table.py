"""leases: the framework's sm_lease table (framework 0.0.38)

Revision ID: b65e04cf65d7
Revises: 30033455948e
Create Date: 2026-10-23

The framework's own revision ``d263ea727663`` (#539), ported into this host's
history, since the host owns its migrations. ``sm_lease`` backs the database
lease backend ``create_app`` installs when ``SM_REDIS_URL`` is unset.

Upstream it is a separate root; here it continues the one linear history like
every other revision, keeping the framework's ``leases`` label as a named
target only (see CLAUDE.md: ``leases@base`` walks everything beneath it).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b65e04cf65d7"
down_revision: str | None = "30033455948e"
branch_labels: str | Sequence[str] | None = ("leases",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sm_lease",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("holder", sa.String(length=255), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name", "slot", name=op.f("pk_sm_lease")),
    )


def downgrade() -> None:
    op.drop_table("sm_lease")
