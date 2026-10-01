"""records content locales: record locale, translation group, translatable type

Revision ID: a7c3e1d4b920
Revises: fccc111ff2e9
Create Date: 2026-09-20 11:05:00.000000

Hand-written, in four places autogenerate cannot reach:

* ``records_record.locale`` is NOT NULL, so it needs a ``server_default`` for
  the rows that already exist. Everything written before this migration is in
  the default content locale by definition — there was no other. The default is
  dropped again afterwards so the application owns the column's default from
  here on.
* ``records_record.translation_group`` is NOT NULL *and* has to differ per row
  (it is half of a unique index), which no ``server_default`` can express
  portably. It goes in nullable, is backfilled from each row's own ``uuid`` —
  which is exactly the rule ``create_record`` applies, so a pre-existing record
  ends up alone in a group named after itself — and is tightened to NOT NULL
  after.
* **The partial unique slug index is dropped and recreated, by hand.**
  ``ix_records_record_type_slug`` keeps its name and gains ``locale`` in the
  middle of its key. Alembic autogenerate compares an index's *name and
  columns* and never its ``WHERE``, and here even the columns change under a
  name that does not — so nothing about this would have been generated, and
  nothing would have reported its absence either (``SM010``/``SM011`` are about
  revisions and tables). The deployed definition is worth checking by hand
  after this runs: ``\\di+ ix_records_record_type_slug`` on Postgres, or
  ``SELECT sql FROM sqlite_master WHERE name = 'ix_records_record_type_slug'``
  on SQLite. Both should read ``(type_id, locale, slug) WHERE slug IS NOT
  NULL``.
* The index drop happens **before** the ``batch_alter_table`` that adds the
  columns, not after. SQLite has no ``ALTER``, so batch mode recreates the
  table and every index on it from what it reflected — and a reflected partial
  index is exactly the thing least likely to survive that round trip intact.
  Dropping it first means batch never sees it.

Downgrading is lossy in the way the pagebuilder revision that did this to
``pagebuilder_pages`` is lossy: recreating the old ``(type_id, slug)`` unique
index fails if two languages have claimed the same slug in one type, which is
the whole point of the upgrade. Resolving those is a data decision, not one a
migration can make.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e1d4b920"
down_revision: str | None = "fccc111ff2e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECORD = "records_record"
_TYPE = "records_type"

_SLUG_INDEX = "ix_records_record_type_slug"
_GROUP_INDEX = "ix_records_record_translation_group"
_GROUP_LOCALE_INDEX = "ix_records_record_group_locale"

_LOCALE_LEN = 16
_GROUP_LEN = 32
_DEFAULT_LOCALE = "en"
"""The language every pre-existing record is in.

A literal rather than a read of the settings store — unlike the equivalent
pagebuilder revision, which had to consult it. ``records`` had no
``content_locales`` setting before this migration, so there is no stored value
to honour: every row predates the feature, and the module's own default is
``"en"``. An install that wants another default sets it afterwards and
translates or re-imports what it has.
"""


def upgrade() -> None:
    # Before the batch below: see the module docstring for why.
    op.drop_index(_SLUG_INDEX, table_name=_RECORD)

    with op.batch_alter_table(_RECORD) as batch:
        batch.add_column(
            sa.Column(
                "locale",
                sa.String(length=_LOCALE_LEN),
                nullable=False,
                server_default=_DEFAULT_LOCALE,
            )
        )
        batch.add_column(
            sa.Column("translation_group", sa.String(length=_GROUP_LEN), nullable=True)
        )

    records = sa.table(
        _RECORD,
        sa.column("uuid", sa.String),
        sa.column("translation_group", sa.String),
    )
    # One group per existing record, named after the record: nothing was a
    # translation of anything before this migration, so every row is a group of
    # one. A single UPDATE rather than a row-at-a-time loop — the column is a
    # copy of one that is already on the row.
    op.get_bind().execute(records.update().values(translation_group=records.c.uuid))

    with op.batch_alter_table(_RECORD) as batch:
        batch.alter_column("locale", server_default=None)
        batch.alter_column(
            "translation_group", existing_type=sa.String(length=_GROUP_LEN), nullable=False
        )

    op.create_index(
        _SLUG_INDEX,
        _RECORD,
        ["type_id", "locale", "slug"],
        unique=True,
        postgresql_where=sa.text("slug IS NOT NULL"),
        sqlite_where=sa.text("slug IS NOT NULL"),
    )
    op.create_index(_GROUP_INDEX, _RECORD, ["translation_group"], unique=False)
    op.create_index(_GROUP_LOCALE_INDEX, _RECORD, ["translation_group", "locale"], unique=True)

    with op.batch_alter_table(_TYPE) as batch:
        batch.add_column(
            sa.Column("translatable", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table(_TYPE) as batch:
        batch.alter_column("translatable", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table(_TYPE) as batch:
        batch.drop_column("translatable")

    op.drop_index(_GROUP_LOCALE_INDEX, table_name=_RECORD)
    op.drop_index(_GROUP_INDEX, table_name=_RECORD)
    op.drop_index(_SLUG_INDEX, table_name=_RECORD)

    with op.batch_alter_table(_RECORD) as batch:
        batch.drop_column("translation_group")
        batch.drop_column("locale")

    # Fails where two locales share a slug within one type — see the module
    # docstring. That is the feature being removed, not a bug in the removal.
    op.create_index(
        _SLUG_INDEX,
        _RECORD,
        ["type_id", "slug"],
        unique=True,
        postgresql_where=sa.text("slug IS NOT NULL"),
        sqlite_where=sa.text("slug IS NOT NULL"),
    )
