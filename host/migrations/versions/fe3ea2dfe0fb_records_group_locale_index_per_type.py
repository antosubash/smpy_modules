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

**Hand-written, and derived from the factory rather than spelled out.** Alembic
autogenerate compares an index's *name and columns*; here the columns change
under a name that does not, which it does detect — but only for the tables it
can see, and the whole point of a collection (§6.1) is that which tables exist
is the host's decision. So this revision asks
:func:`sm_records.models.table_sets` for the declared sets and rewrites each
one's own index, under each one's own name. A host that declares no collection
rewrites exactly one index; this repo's demo host, which declares ``events``,
rewrites two. That is the same property ``3b4733cf5444`` expresses by being a
separate revision, said in code instead.

Downgrading is lossy in the same way ``a7c3e1d4b920``'s is: recreating the
narrower index fails if two *types* have come to share a ``(translation_group,
locale)`` pair while this one was in force, which is precisely what the upgrade
makes legal. Resolving that is a data decision.
"""

from collections.abc import Sequence

from alembic import op

from sm_records.models import table_sets

# revision identifiers, used by Alembic.
revision: str = "fe3ea2dfe0fb"
down_revision: str | None = "3b4733cf5444"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = ["type_id", "translation_group", "locale"]
_OLD = ["translation_group", "locale"]


def _rewrite(columns: list[str]) -> None:
    for tables in table_sets():
        name = tables.group_locale_index
        table = tables.record.__tablename__
        op.drop_index(name, table_name=table)
        op.create_index(name, table, columns, unique=True)


def upgrade() -> None:
    _rewrite(_NEW)


def downgrade() -> None:
    _rewrite(_OLD)
