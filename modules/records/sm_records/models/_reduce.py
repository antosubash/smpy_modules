"""The reduce index — one maintained aggregate row per ``(type, key, group)``.

Phase 5 §5.2, and the one table in this module that is **not** a projection of
a document. Every ``records_index_*`` table holds rows derived from one record
and keyed on its id; this one holds a *fold* over many records, so no row here
belongs to a record and no row is rebuilt by rewriting a record's own.

That difference is the whole cost of the feature and the reason §7.5 refused
it in v1: an aggregate maintained on write is a second source of truth, and a
second source of truth can drift. Three things keep it honest, and all three
have to exist together — the delta inside the write transaction
(:mod:`sm_records.index.reduce`), the from-scratch rebuild and the verifier
(:mod:`sm_records.index.reduce_rebuild`). Drift is therefore *detectable*,
which is the answer to §7.5 rather than a denial of it.

**Inert when unused.** No spec registered means nothing ever writes here, and
an install that registers none pays exactly the Phase 4 write path — the
registry is empty, so the writer's reduce pass is a ``for`` over nothing.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric
from sqlmodel import Field

from sm_records.constants import (
    MAX_KEY_LEN,
    NUMBER_PRECISION,
    NUMBER_SCALE,
    REDUCE_GROUP_LEN,
)
from sm_records.models._base import INDEX_REDUCE_TABLE, Base

REDUCE_GROUP_INDEX_NAME = f"uq_{INDEX_REDUCE_TABLE}_group"
"""The unique index on ``(type_id, key, group_value)``.

Named here because two layers need the name: the table definition below and
:func:`sm_records.index.reduce.bump`, which recognises the database's own
refusal of a racing first insert and retries the increment instead — exactly
the pattern :data:`sm_records.models.SLUG_CONFLICT_SIGNATURES` documents for
the slug claim, and for the same reason.
"""


class IndexReduce(Base, table=True):  # ty: ignore[unsupported-base]
    """One group of one reduce spec on one type.

    ``count`` is how many live records fall in the group and ``sum`` the fold
    of the spec's ``value`` over them (``NULL`` for a spec that declares none).
    A group whose ``count`` reaches zero is deleted rather than left at zero:
    the table is then exactly the set of non-empty groups, which is what makes
    "the stored rows" and "a fresh recompute" comparable row for row — the
    property :func:`sm_records.index.reduce_rebuild.verify_type` checks.

    There is no ``record_id`` and no foreign key. A row here is a fold over
    records, not a projection of one, so nothing cascades into it: the writer
    maintains it by delta and a type delete removes its rows explicitly
    (``services._lifecycle.purge_type_records``).
    """

    __tablename__ = INDEX_REDUCE_TABLE
    __table_args__ = (
        Index(REDUCE_GROUP_INDEX_NAME, "type_id", "key", "group_value", unique=True),
        # The read shape: every group of one spec on one type, which the
        # aggregate endpoint then orders by count. Distinct from the unique
        # index above only in that it stops before ``group_value``; kept
        # separate because a planner will not use a unique index's prefix for
        # a range scan on every backend.
        Index(f"ix_{INDEX_REDUCE_TABLE}_lookup", "type_id", "key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    type_id: int = Field(sa_column_kwargs={"nullable": False})
    key: str = Field(max_length=MAX_KEY_LEN, sa_column_kwargs={"nullable": False})
    """The spec's key — a virtual key, reserved and owned exactly as an index
    provider's :class:`~sm_records.index.providers.VirtualField` key is."""
    group_value: str = Field(max_length=REDUCE_GROUP_LEN, sa_column_kwargs={"nullable": False})
    """The group, rendered as text whatever the spec returned.

    One column for every kind of group, because a reduce spec is a Python
    callable and the module cannot know in advance whether it folds on a
    string, a date or a number. Truncated at :data:`REDUCE_GROUP_LEN`, which
    is the same ceiling — and the same arithmetic — as ``TEXT_INDEX_LEN``.
    """
    count: int = Field(sa_column_kwargs={"nullable": False})
    sum: Decimal | None = Field(
        default=None, sa_type=Numeric(NUMBER_PRECISION, NUMBER_SCALE), nullable=True
    )
    """``NULL`` for a spec with no ``value``; never confused with ``0``, which
    is a real fold of values that cancel."""
    updated_at: datetime = Field(
        sa_type=DateTime(timezone=True), sa_column_kwargs={"nullable": False}
    )
