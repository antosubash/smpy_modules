"""records invalid_since: the stored "this record does not fit the schema" mark

Revision ID: 8f3d223f8605
Revises: d2b7a1c4e905
Create Date: 2026-09-22 13:45:13.873103

``<table set>_record.invalid_since`` is when a record stopped satisfying its
type's schema, or ``NULL``. Design §8.3 has always said a record a forced
restrictive change leaves behind is *marked, not hidden*, and the mark was
derived on read — one validator pass per record, which the list deliberately
turns off — so nothing could show a badge on a row, count the marked records
or filter for them. This is the same mark, stored: written by the scan of a
forced change and by a rescan, cleared by the record's next successful write.

**Nullable, with no server default and no backfill.** ``NULL`` is exactly the
right answer for every row that exists: nothing has scanned them under this
feature, and inventing a timestamp would claim a check that never ran. The
existing derived badge is unchanged, so an upgraded install reads identically
until the next forced change or "Check records" marks anything.

**Every table set gains it.** A collection's document table is built by the
same factory as the global one (Phase 5 §6), so ``tables_for()`` would
otherwise hand the query layer a table without the column the grammar's
``invalid`` filter compiles to. The demo host's one collection is here by
name for the reason index names are: a table set's DDL is spelled from its own
prefix.

The index is the plain single-column one the model declares. A page's
predicate is ``type_id = :t AND invalid_since IS NOT NULL``, and the marked
records are the rare ones — which is what makes an index on the column worth
its inserts even though it is not the composite the sorted page would prefer.

Downgrading drops column and index, which loses only which records were
marked; the derived badge survives it, and the next rescan re-derives the list.
"""


from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8f3d223f8605'
down_revision: str | None = 'd2b7a1c4e905'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'records_c_events_record',
        sa.Column('invalid_since', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f('ix_records_c_events_record_invalid_since'),
        'records_c_events_record',
        ['invalid_since'],
        unique=False,
    )
    op.add_column(
        'records_record',
        sa.Column('invalid_since', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f('ix_records_record_invalid_since'),
        'records_record',
        ['invalid_since'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_records_record_invalid_since'), table_name='records_record')
    op.drop_column('records_record', 'invalid_since')
    op.drop_index(
        op.f('ix_records_c_events_record_invalid_since'),
        table_name='records_c_events_record',
    )
    op.drop_column('records_c_events_record', 'invalid_since')
