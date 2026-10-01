"""Reduce indexes — a maintained aggregate, kept by delta inside the write.

Phase 5 §5.2. A :class:`ReduceSpec` folds every record of a type into one row
per group in ``records_index_reduce``; the writer applies the *difference*
between what a record contributed before a write and what it contributes
after, so the cost is one statement per spec per write rather than a scan.

This module is the **spec and the projection**: what a record contributes.
The statements that move a stored group live next door in
:mod:`sm_records.index._reduce_write`, split along the seam
``providers``/``_registry`` already draws — one owner for the fold, one for
the SQL that stores it.

Three properties are the whole design, and none of them survives on its own:

* **Delta, never read-modify-write.** The increment is
  ``UPDATE … SET count = count + :dc`` — arithmetic the database does — so two
  writers cannot both read ``7`` and both store ``8``. On SQLite the type-row
  lock (``services._claims.lock_type``) already serialises writers; on
  Postgres the row ``UPDATE`` does, because the second writer blocks on the
  first's uncommitted row until it commits and then re-reads it.
* **Derivable.** :func:`sm_records.index.reduce_rebuild.rebuild_type` throws
  the rows away and recomputes them from the records, so the reduce table is
  never more than a cache of something the documents already say.
* **Verifiable.** :func:`sm_records.index.reduce_rebuild.verify_type` compares
  the two. Design §7.5's objection to a maintained aggregate was drift, and
  the honest answer is not "it cannot drift" but "drift is detected".

**Inert when unused.** With no spec registered every function here returns
after a ``for`` over an empty tuple and no statement is issued — which is what
makes the Phase 4 write path's statement count unchanged on an install that
never asked for this.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sm_records.constants import REDUCE_GROUP_LEN
from sm_records.index import _registry
from sm_records.models import Record, RecordType

logger = logging.getLogger(__name__)

__all__ = [
    "ReduceSpec",
    "clear_reduce_providers",
    "contribution",
    "group_text",
    "reduce_specs",
    "register_reduce_provider",
    "snapshot",
    "spec_for",
]

GroupBy = Callable[[Record, RecordType], Any]
ValueOf = Callable[[Record, RecordType], Decimal | None]


@dataclass(frozen=True, slots=True)
class ReduceSpec:
    """One maintained aggregate: how a record picks its group, and what it adds.

    ``group_by`` returns the group a record belongs to, or ``None`` for a
    record that belongs in none — which is how a spec declines a record
    rather than inventing an "unknown" bucket. Whatever it returns is rendered
    to text (:func:`group_text`), because one column has to hold the groups of
    every spec and the module cannot know in advance whether a host folds on a
    string, a date or a number.

    ``value`` is optional. Without it the row carries only ``count`` and its
    ``sum`` stays ``NULL``; with it the row also folds the returned
    :class:`~decimal.Decimal` over the group's records. ``None`` from
    ``value`` is *zero contribution*, not "no group" — a record with no price
    still counts.

    ``key`` is a virtual key: reserved, validated and owned exactly as an
    index provider's :class:`~sm_records.index.providers.VirtualField` key is,
    and refused as a declared field key on save.

    ``value_label`` is what a reading of this spec calls the quantity it sums —
    free text for a human, and the only thing the ``metric`` field of an
    aggregate response can honestly say about a stored fold. A live aggregate's
    ``metric`` is ``sum:<field>`` and names a **field**; a spec has no field,
    it has a callable, so reporting ``sum:<spec key>`` there read as a field
    that does not exist. Without a label the metric is the bare ``"sum"``.
    """

    key: str
    group_by: GroupBy
    value: ValueOf | None = None
    value_label: str | None = None


_specs: dict[str, ReduceSpec] = {}


def register_reduce_provider(spec: ReduceSpec) -> None:
    """Register a maintained aggregate. Idempotent on the same spec object.

    Call it at import time or from a module's ``on_startup``; the registry is
    process-global, so **every worker must run the same registrations** or one
    of them will write deltas the others do not.

    Registering a spec against a type that already holds records does **not**
    mark anything ``reindex_pending``: a provider is code the host deploys,
    not a schema edit this module can see, which is the same rule virtual
    fields follow. Run ``python -m sm_records.cli reindex`` afterwards — until
    then the table simply has no rows for the new key, and the aggregate
    endpoint's live ``GROUP BY`` is unaffected either way.
    """
    _registry.claim_reduce(spec.key, spec)
    _specs[spec.key] = spec


def reduce_specs() -> tuple[ReduceSpec, ...]:
    """Every registered spec, in registration order."""
    return tuple(_specs.values())


def spec_for(key: str) -> ReduceSpec | None:
    return _specs.get(key)


def clear_reduce_providers() -> None:
    """Drop every registered spec and the keys they claimed — the state a
    fresh import gives. The test-suite counterpart of
    :func:`sm_records.index.providers.clear`."""
    _specs.clear()
    _registry.clear_reduce()


def group_text(value: Any) -> str | None:
    """Render a group as the text the column stores, or ``None`` for no group.

    Rendered in Python rather than cast in SQL so the same string is produced
    on SQLite and Postgres — the group is half of a unique index, and two
    backends spelling a date differently would silently split one group in
    two on a migration between them. ``date``/``datetime`` go through
    ``isoformat`` for the same reason, and everything else through ``str``.

    Truncated at :data:`~sm_records.constants.REDUCE_GROUP_LEN`, which is the
    §7.4 truncation applied to a fold: two groups differing only after the cut
    merge into one. A spec grouping on free text rather than on a bounded
    value is asking for that, and the README says so.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)[:REDUCE_GROUP_LEN]


def _decimal(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def contribution(spec: ReduceSpec, record: Record, rtype: RecordType) -> tuple[str, Decimal] | None:
    """What one record adds to one spec: ``(group, value)``, or ``None``.

    **A spec that raises contributes nothing and is logged**, the same
    isolation :func:`sm_records.index.writer.project` gives an index provider
    and for the same reason: a host's broken extension must not make every
    record of every type unsaveable. The cost is different here, though, and
    worth being explicit about — a failure on the *old* side of a delta leaves
    the group it was in over-counted until the next rebuild, which is exactly
    the drift :func:`sm_records.index.reduce_rebuild.verify_type` exists to
    find.
    """
    try:
        group = group_text(spec.group_by(record, rtype))
        if group is None:
            return None
        amount = _decimal(spec.value(record, rtype)) if spec.value is not None else None
    except Exception:
        logger.exception(
            "records: reduce spec %r failed on record %s; its contribution is missing "
            "until the next rebuild",
            spec.key,
            record.uuid,
        )
        return None
    return group, amount if amount is not None else Decimal(0)


class _Snapshot:
    """A record as it was before this write, for the delta's *old* side.

    A proxy rather than a copy: ``Record`` is an instrumented SQLAlchemy
    instance, and copying one produces an object the session may or may not
    consider its own. Everything but ``data`` reads through to the live row —
    which is the honest reading of "previous" for a payload write, the only
    thing an update changes that a spec can fold on.
    """

    __slots__ = ("_record", "data")

    def __init__(self, record: Record, data: dict[str, Any] | None) -> None:
        self._record = record
        self.data = data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._record, name)


def snapshot(record: Record, data: dict[str, Any] | None) -> Record:
    """The ``before`` argument of :func:`apply_delta` for a record being
    *replaced* — its live row with ``data`` as it was read."""
    return _Snapshot(record, data)  # ty: ignore[invalid-return-type]
