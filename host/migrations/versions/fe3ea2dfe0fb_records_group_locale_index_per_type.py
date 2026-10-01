"""records: scope the (translation_group, locale) unique index by type

Revision ID: fe3ea2dfe0fb
Revises: 3b4733cf5444
Create Date: 2026-09-20 13:40:00.000000

Phase 5 §4.3 states the rule as "one record per ``(translation_group,
locale)``", and every reader of a group scopes by type
(``list_translations``, ``_sibling``, ``published_siblings``). The index did
not, so it was wider than the concept it enforced: an import into type ``memo``
naming a group that exists in type ``art`` was refused with "a memo record in
'en' already exists in that translation group" — a refusal naming a record that
does not exist, and a coupling between two types that share nothing. ``type_id``
leads the key from here on.

**Hand-written, and applied to the tables this database actually has.** Alembic
autogenerate compares an index's *name and columns*; here the columns change
under a name that does not, which it does detect — but only for the tables it
can see, and the whole point of a collection (§6.1) is that which tables exist
is the host's decision. So the index name and its table are taken from
:func:`sm_records.models.table_sets`, and *which* of those sets to touch is
taken from the database — see :func:`_present_sets` for why the two are not the
same question. A host that has only the global document table rewrites exactly
one index; this repo's demo host, which declares ``events`` and whose tables
``3b4733cf5444`` creates directly beneath, rewrites two.

Downgrading is lossy in the same way ``a7c3e1d4b920``'s is: recreating the
narrower index fails if two *types* have come to share a ``(translation_group,
locale)`` pair while this one was in force, which is precisely what the upgrade
makes legal. Resolving that is a data decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sm_records.models import TableSet, table_sets

# revision identifiers, used by Alembic.
revision: str = "fe3ea2dfe0fb"
down_revision: str | None = "3b4733cf5444"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = ["type_id", "translation_group", "locale"]
_OLD = ["translation_group", "locale"]


def _present_sets() -> tuple[TableSet, ...]:
    """The declared table sets whose document table exists **in this database**.

    A revision acts on the tables that exist at *its* point in the chain, and
    that is not what ``table_sets()`` answers on its own: that is what the host
    declares **today**. The difference is the whole bug this function exists to
    prevent. A host that declares a collection after this revision was written
    autogenerates its tables at the then-current head — i.e. *above* here — so
    on a fresh database the chain reaches this revision with those tables not
    yet created, and a blind ``DROP INDEX`` fails with ``no such index:
    ix_records_c_<name>_record_group_locale``. Nothing is lost by skipping
    them: a collection created above this point gets its indexes from its own
    creation migration, which autogenerate writes from the *current* model and
    which therefore already carries ``(type_id, translation_group, locale)``
    (and the descending indexes ``c4a17b9de0f2`` adds) — verified by
    autogenerating a scratch collection against a database at head.

    So: ask the database which ``records_record``-shaped tables it has
    (``records_record`` and ``records_c_<name>_record``) and skip any declared
    set that is not among them. The global set is always present — it is
    created far below, in ``e23090832709``.

    Offline (``--sql``) there is no database to ask and a generated script
    cannot branch on one, so every declared set is emitted: that is the right
    answer for the host the script is being generated for, which is the host
    whose declarations are loaded.
    """
    if op.get_context().as_sql:
        return table_sets()
    present = set(sa.inspect(op.get_bind()).get_table_names())
    return tuple(tables for tables in table_sets() if tables.record.__tablename__ in present)


def _rewrite(columns: list[str]) -> None:
    for tables in _present_sets():
        name = tables.group_locale_index
        table = tables.record.__tablename__
        op.drop_index(name, table_name=table)
        op.create_index(name, table, columns, unique=True)


def upgrade() -> None:
    _rewrite(_NEW)


def downgrade() -> None:
    _rewrite(_OLD)
