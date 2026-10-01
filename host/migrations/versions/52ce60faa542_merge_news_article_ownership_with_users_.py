"""merge news article ownership with users and records

Revision ID: 52ce60faa542
Revises: d4e7c1a9b602, 25633593dd54
Create Date: 2026-10-01 15:38:46.526402

An empty merge point. ``d4e7c1a9b602`` ends the line on which a news article
stopped being a sidecar over a page and became multilingual;
``25633593dd54`` ends the users and records line that landed on ``main`` in
parallel. Neither touches the other's tables, so there is nothing to order —
this only gives ``alembic upgrade head`` one head to reach again.

As with ``d4e7c1a9b602``, ``alembic downgrade -1`` from here is ambiguous;
name the parent you want instead.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "52ce60faa542"
down_revision: str | tuple[str, ...] | None = ("d4e7c1a9b602", "25633593dd54")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
