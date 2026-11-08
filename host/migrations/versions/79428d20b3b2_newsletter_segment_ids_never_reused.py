"""newsletter segment ids never reused

A campaign names its audience ``segment:<id>``. On SQLite a plain ``INTEGER
PRIMARY KEY`` hands the highest id out again once that row is deleted, so a
draft whose segment was deleted would silently re-bind to the next segment
created. This recreates ``newsletter_segment`` with ``AUTOINCREMENT`` on SQLite
(data, the tenant index and ``uq_newsletter_segment_name`` kept). Postgres
sequences never reuse an id, so it is a no-op there. No branch label.

Revision ID: 79428d20b3b2
Revises: ce8aa53ead7d
Create Date: 2026-11-08 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "79428d20b3b2"
down_revision: str | None = "ce8aa53ead7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recreate(*, autoincrement: bool) -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table(
        "newsletter_segment",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": autoincrement},
    ):
        pass


def upgrade() -> None:
    _recreate(autoincrement=True)


def downgrade() -> None:
    _recreate(autoincrement=False)
