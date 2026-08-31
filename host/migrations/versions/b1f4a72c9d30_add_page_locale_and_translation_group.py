"""add page locale and translation group

Revision ID: b1f4a72c9d30
Revises: 6504b2249610
Create Date: 2026-08-22 14:40:00.000000

Hand-adjusted from autogenerate in three places:

* ``locale`` is NOT NULL, so it needs a ``server_default`` for the rows that
  already exist. Everything written before this migration is in the default
  content locale by definition — that is the language whose pages keep serving
  at the unprefixed URL. The default is dropped again afterwards so the
  application owns the column's default from here on.
* ``translation_group`` is NOT NULL *and* has to differ per row (it is half of
  a unique index), which no ``server_default`` can express portably. It goes in
  nullable, gets a generated value per existing page, and is tightened to NOT
  NULL after.
* The slug unique index is replaced rather than added to: slugs are unique per
  language now, so the old single-column index would forbid exactly the case
  this change exists to allow — the same word as the address in two languages.
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1f4a72c9d30"
down_revision: str | None = "6504b2249610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAGES = "pagebuilder_pages"
_REDIRECTS = "pagebuilder_page_redirects"
_LOCALE_LEN = 12

# Read straight out of the settings table rather than through
# ``PagebuilderSettings``: a migration that constructs application settings
# starts failing whenever an unrelated required setting is added, and this is
# the only value it needs. The store is also the *only* place the value can
# come from — pagebuilder reads no environment variables — so an absent row
# means the class default, which ``_FALLBACK_LOCALE`` repeats.
_SETTINGS_TABLE = "settings_setting"
_LOCALE_KEY = "pagebuilder.default_content_locale"
_FALLBACK_LOCALE = "en"

_SETTINGS = sa.table(
    _SETTINGS_TABLE,
    sa.column("scope", sa.String),
    sa.column("scope_id", sa.String),
    sa.column("key", sa.String),
    sa.column("value", sa.String),
)


def _default_locale(bind: sa.Connection) -> str:
    """The language every pre-existing page is in, per the settings store.

    ``default_content_locale`` is a plain ``str``, so the store holds it
    verbatim rather than JSON-encoded. The table is checked for rather than
    assumed: it is created by the initial revision this one descends from, but
    a host that mounts pagebuilder without the Settings module would otherwise
    fail here instead of backfilling the default.
    """
    if not sa.inspect(bind).has_table(_SETTINGS_TABLE):
        return _FALLBACK_LOCALE
    stored = bind.scalar(
        sa.select(_SETTINGS.c.value).where(
            _SETTINGS.c.scope == "system",
            _SETTINGS.c.scope_id == "",
            _SETTINGS.c.key == _LOCALE_KEY,
        )
    )
    return (stored or "").strip() or _FALLBACK_LOCALE


def upgrade() -> None:
    locale = _default_locale(op.get_bind())

    with op.batch_alter_table(_PAGES) as batch:
        batch.add_column(
            sa.Column(
                "locale",
                sa.String(length=_LOCALE_LEN),
                nullable=False,
                server_default=locale,
            )
        )
        batch.add_column(
            sa.Column("translation_group", sa.String(length=32), nullable=True)
        )

    bind = op.get_bind()
    pages = sa.table(
        _PAGES,
        sa.column("id", sa.Integer),
        sa.column("translation_group", sa.String),
    )
    # One group per existing page: nothing was a translation of anything before
    # this migration, so every row is a group of one.
    for (page_id,) in bind.execute(sa.select(pages.c.id)).all():
        bind.execute(
            pages.update()
            .where(pages.c.id == page_id)
            .values(translation_group=uuid4().hex)
        )

    op.drop_index(op.f("ix_pagebuilder_pages_slug"), table_name=_PAGES)
    with op.batch_alter_table(_PAGES) as batch:
        batch.alter_column("locale", server_default=None)
        batch.alter_column(
            "translation_group",
            existing_type=sa.String(length=32),
            nullable=False,
        )
    op.create_index(
        "ix_pagebuilder_pages_locale_slug", _PAGES, ["locale", "slug"], unique=True
    )
    op.create_index(
        "ix_pagebuilder_pages_group_locale",
        _PAGES,
        ["translation_group", "locale"],
        unique=True,
    )

    with op.batch_alter_table(_REDIRECTS) as batch:
        batch.add_column(
            sa.Column(
                "locale",
                sa.String(length=_LOCALE_LEN),
                nullable=False,
                server_default=locale,
            )
        )
    op.drop_index(
        op.f("ix_pagebuilder_page_redirects_from_slug"), table_name=_REDIRECTS
    )
    with op.batch_alter_table(_REDIRECTS) as batch:
        batch.alter_column("locale", server_default=None)
    op.create_index(
        "ix_pagebuilder_page_redirects_locale_from_slug",
        _REDIRECTS,
        ["locale", "from_slug"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pagebuilder_page_redirects_locale_from_slug", table_name=_REDIRECTS
    )
    with op.batch_alter_table(_REDIRECTS) as batch:
        batch.drop_column("locale")
    op.create_index(
        op.f("ix_pagebuilder_page_redirects_from_slug"),
        _REDIRECTS,
        ["from_slug"],
        unique=True,
    )

    op.drop_index("ix_pagebuilder_pages_group_locale", table_name=_PAGES)
    op.drop_index("ix_pagebuilder_pages_locale_slug", table_name=_PAGES)
    with op.batch_alter_table(_PAGES) as batch:
        batch.drop_column("translation_group")
        batch.drop_column("locale")
    # Re-creating the global unique index fails if two languages had claimed
    # the same slug — which is the whole point of the upgrade. Downgrading a
    # database that used the feature therefore needs those resolved first;
    # that is a data decision, not one a migration can make.
    op.create_index(
        op.f("ix_pagebuilder_pages_slug"), _PAGES, ["slug"], unique=True
    )
