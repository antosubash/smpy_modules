"""add page SEO title, nav flags and redirects

Revision ID: 7327cb99fe0a
Revises: 7a776d0b6240
Create Date: 2026-08-19 17:05:00.000000

Hand-adjusted from autogenerate: the two boolean columns are NOT NULL and need
``server_default`` values for the backfill, dropped again afterwards so the
application owns the default from here on. ``meta_title`` is nullable, which is
the point — null means "use the page title", and that is the common case.

Both nav flags backfill to false: nothing was in the header or footer nav before
this column existed, so defaulting to true would silently add every page on the
site to the navigation on deploy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7327cb99fe0a"
down_revision: str | None = "7a776d0b6240"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAGES = "pagebuilder_pages"
_REDIRECTS = "pagebuilder_page_redirects"


def upgrade() -> None:
    op.create_table(
        _REDIRECTS,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_slug", sa.String(length=200), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_id"],
            [f"{_PAGES}.id"],
            name=op.f("fk_pagebuilder_page_redirects_page_id_pagebuilder_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pagebuilder_page_redirects")),
    )
    op.create_index(
        op.f("ix_pagebuilder_page_redirects_from_slug"),
        _REDIRECTS,
        ["from_slug"],
        unique=True,
    )
    op.create_index(
        op.f("ix_pagebuilder_page_redirects_page_id"), _REDIRECTS, ["page_id"], unique=False
    )

    with op.batch_alter_table(_PAGES) as batch:
        batch.add_column(sa.Column("meta_title", sa.String(length=200), nullable=True))
        batch.add_column(
            sa.Column(
                "show_in_header_nav",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "show_in_footer", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )

    op.create_index(
        op.f("ix_pagebuilder_pages_show_in_header_nav"),
        _PAGES,
        ["show_in_header_nav"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pagebuilder_pages_show_in_footer"), _PAGES, ["show_in_footer"], unique=False
    )

    with op.batch_alter_table(_PAGES) as batch:
        batch.alter_column("show_in_header_nav", server_default=None)
        batch.alter_column("show_in_footer", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_pagebuilder_pages_show_in_footer"), table_name=_PAGES)
    op.drop_index(op.f("ix_pagebuilder_pages_show_in_header_nav"), table_name=_PAGES)
    with op.batch_alter_table(_PAGES) as batch:
        batch.drop_column("show_in_footer")
        batch.drop_column("show_in_header_nav")
        batch.drop_column("meta_title")

    op.drop_index(op.f("ix_pagebuilder_page_redirects_page_id"), table_name=_REDIRECTS)
    op.drop_index(op.f("ix_pagebuilder_page_redirects_from_slug"), table_name=_REDIRECTS)
    op.drop_table(_REDIRECTS)
