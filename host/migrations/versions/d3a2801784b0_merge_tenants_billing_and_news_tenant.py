"""merge tenants, billing and news tenant heads

Revision ID: d3a2801784b0
Revises: 4ae4d020a2f2, 7c1e0b9d4a21, bcf730fac78d
Create Date: 2026-10-19 21:21:23.230950

An empty merge point (#107). Three lines grew from ``25633593dd54`` in
parallel: the framework's tenants/users/file_storage revisions (ending at
``4ae4d020a2f2``), billing (``7c1e0b9d4a21``) and the pagebuilder/news
``tenant_id`` line (``bcf730fac78d``). None touches another's tables, so there
is nothing to order — this only gives the history one head again, so
``alembic revision --autogenerate`` (``make migration``) works and
``downgrade -1`` stops picking a branch. CI's "Single migration head" step
keeps it that way.

As with ``52ce60faa542``, ``alembic downgrade -1`` *from here* is ambiguous;
name the parent you want instead.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d3a2801784b0"
down_revision: str | tuple[str, ...] | None = ("4ae4d020a2f2", "7c1e0b9d4a21", "bcf730fac78d")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
