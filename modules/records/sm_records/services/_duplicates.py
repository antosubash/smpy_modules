"""Would turning ``unique`` on refuse the records that already exist?

Design doc §8.2 classifies ``unique_added`` as **restrictive**, and §8.2's
contract for restrictive is "only after a clean dry run, or under ``force``".
The dry run, though, validates *one record's payload at a time* against the
proposed model, and duplication is a property of a **pair** of records: no
per-record validation can see it. So the guard ran, reported clean, and the
change applied — leaving two records sharing a value, each of which
:func:`sm_records.services._claims.ensure_unique` then refused every write to,
because it found the other's index row.

This module is the missing half of that scan. Two paths, because a newly
unique field may or may not already be indexed:

* **Indexed already** — one ``GROUP BY … HAVING`` per key against the index
  table the field projects into. Grouping is on ``value`` *and* ``value_full``
  together, which is the §7.4 truncation re-check spelled as a grouping rather
  than as a predicate: two values that differ only past ``TEXT_INDEX_LEN``
  share a ``value`` and are not duplicates. The index table carries no record
  state, so nothing scopes the group to the living — the trash counts, exactly
  as ``ensure_unique``'s ``include_deleted`` makes it count.
* **Not indexed yet** — ``unique`` normalises to imply ``indexed``
  (``schema.fields._validate_flags``), so a field gaining both at once has no
  index rows to group and the query above would report a clean type that is
  not. :class:`Collector` rides along on the scan
  :mod:`sm_records.services._dry_run` is already making, which reads every
  record of the type under the proposed definitions.

Both honour the rule ``ensure_unique`` actually enforces, which is not "no two
records share a value" but "no two *translation groups* do": siblings are
exempt from each other's claims (Phase 5 §4.3), or a German product could not
carry the English product's SKU.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

from sqlalchemy import and_, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import RecordType, tables_for
from sm_records.schema.changes import DRY_RUN_SAMPLE, FailingRecord, SchemaDiff
from sm_records.schema.compile import from_stored
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import INDEX_KIND
from sm_records.services import _claims
from sm_records.services._payload import field_defs
from sm_records.tenancy import bound_tenant

__all__ = ["Collector", "DuplicateReport", "conflicts_for", "newly_unique", "scan"]

GROUP_LIMIT = 200
"""How many duplicated values one key's ``GROUP BY`` reports.

A bound rather than a full list: the answer is a refusal either way, and the
operator is shown ``DRY_RUN_SAMPLE`` of them. A type with more than this many
duplicated values under-reports its count, which the refusal wording allows
for by not claiming the number is exhaustive.
"""


class DuplicateReport(NamedTuple):
    """What one scan contributes to a :class:`
    ~sm_records.schema.changes.DryRunReport`: how many records hold a value
    the new ``unique`` flag would refuse, a few of them to show, and the count
    per field key for the refusal wording."""

    failing: int = 0
    sample: tuple[FailingRecord, ...] = ()
    per_key: dict[str, int] = {}  # noqa: RUF012 - a NamedTuple default, never mutated


def _error(key: str, value: Any) -> dict[str, str]:
    return {
        "field": key,
        "message": f"{value!r} is already held by another record; {key!r} is being made unique",
    }


def newly_unique(
    diff: SchemaDiff, old_defs: list[FieldDefinition], new_defs: list[FieldDefinition]
) -> list[tuple[FieldDefinition, FieldDefinition]]:
    """``(old, new)`` for every key whose diff carries ``unique_added``.

    Both halves, because which of them the scan reads depends on the question:
    where the rows are now is the *old* definition's business (its type
    decides the index table, its ``indexed`` decides whether there are rows at
    all), while what the value will mean is the new one's.
    """
    keys = [c.field_key for c in diff.changes if c.what == "unique_added"]
    old_by_key = {f.key: f for f in old_defs}
    new_by_key = {f.key: f for f in new_defs}
    pairs = []
    for key in keys:
        old, new = old_by_key.get(key), new_by_key.get(key)
        if old is not None and new is not None:
            pairs.append((old, new))
    return pairs


async def _scan_one(
    db: AsyncSession, rtype: RecordType, old: FieldDefinition, *, room: int
) -> tuple[int, list[FailingRecord]]:
    table = tables_for(rtype).index[INDEX_KIND[old.type]]
    record = tables_for(rtype).record
    group_cols = [table.value]
    if hasattr(table, "value_full"):
        group_cols.append(table.value_full)
    # ``record`` is only a join target here, which the framework's tenant
    # filter never reaches (tenancy design FACT 1d): the explicit predicate is
    # §E's rule, redundant with ``type_id`` only while the composite key holds.
    scoped = (
        select(*group_cols, func.count().label("n"))
        .select_from(table)
        .join(record, record.id == table.record_id)
        .where(
            table.type_id == rtype.id,
            table.field_key == old.key,
            record.tenant_id == bound_tenant(),
        )
        .group_by(*group_cols)
        .having(func.count(distinct(record.translation_group)) > 1)
        .limit(GROUP_LIMIT)
        .execution_options(include_deleted=True)
    )
    groups = (await db.execute(scoped)).all()
    if not groups:
        return 0, []
    failing = sum(int(row[-1]) for row in groups)
    if room <= 0:
        return failing, []
    match = or_(
        *(
            and_(*(col == value for col, value in zip(group_cols, row[:-1], strict=False)))
            for row in groups[:room]
        )
    )
    rows = (
        await db.execute(
            select(record.uuid, record.display_title, table.value)
            .select_from(record)
            .join(table, table.record_id == record.id)
            .where(table.type_id == rtype.id, table.field_key == old.key, match)
            .order_by(record.id)
            .limit(room)
            .execution_options(include_deleted=True)
        )
    ).all()
    sample = [
        FailingRecord(uuid=uuid, display_title=title or "", errors=(_error(old.key, value),))
        for uuid, title, value in rows
    ]
    return failing, sample


class Collector:
    """Duplicate detection for keys that have no index rows yet.

    Fed one record at a time by the scan in
    :mod:`sm_records.services._dry_run`, with the coerced view that scan has
    already computed — so this costs no query and no second walk. It holds one
    ``{value: translation_group}`` entry per distinct value per key, which is
    the same order of memory as the payload pass it rides on.
    """

    def __init__(self, defs: Sequence[FieldDefinition]) -> None:
        self._keys = [f.key for f in defs]
        self._seen: dict[str, dict[Any, str]] = {key: {} for key in self._keys}
        self._hits: dict[str, int] = dict.fromkeys(self._keys, 0)
        self._sample: list[FailingRecord] = []

    @property
    def active(self) -> bool:
        return bool(self._keys)

    def add(self, record: Any, values: dict[str, Any], *, room: int) -> None:
        for key in self._keys:
            value = values.get(key)
            if value is None:
                continue
            try:
                owner = self._seen[key].setdefault(value, record.translation_group)
            except TypeError:  # unhashable — a value no unique field can hold
                continue
            if owner == record.translation_group:
                continue
            self._hits[key] += 1
            if len(self._sample) < room:
                self._sample.append(
                    FailingRecord(
                        uuid=record.uuid,
                        display_title=record.display_title or "",
                        errors=(_error(key, value),),
                    )
                )

    def report(self) -> DuplicateReport:
        """Counts the *second and later* holders of each value, plus one for
        the first: the record that established the value is as unsaveable as
        the one that repeated it, so both belong in the count."""
        per_key = {key: hits + 1 for key, hits in self._hits.items() if hits}
        return DuplicateReport(sum(per_key.values()), tuple(self._sample), per_key)


async def scan(
    db: AsyncSession,
    rtype: RecordType,
    pairs: Sequence[tuple[FieldDefinition, FieldDefinition]],
    *,
    room: int = DRY_RUN_SAMPLE,
) -> DuplicateReport:
    """The indexed half — one ``GROUP BY`` per already-indexed key."""
    failing = 0
    sample: list[FailingRecord] = []
    per_key: dict[str, int] = {}
    for old, _new in pairs:
        if not old.indexed:
            continue
        count, rows = await _scan_one(db, rtype, old, room=max(room - len(sample), 0))
        if count:
            per_key[old.key] = count
            failing += count
            sample.extend(rows)
    return DuplicateReport(failing, tuple(sample[:room]), per_key)


async def conflicts_for(db: AsyncSession, rtype: RecordType, record: Any) -> list[dict[str, str]]:
    """The ``invalid`` entries a record left duplicated by a forced change wears.

    §8.3's badge is "marked, not hidden", and until this existed a duplicate
    was the one restrictive failure that produced no mark at all: the compiled
    validator sees one payload, and this record's payload is perfectly valid —
    it is the *pair* that is not. The editor therefore showed a clean record
    that no write would be accepted for.

    One existence check per ``unique`` field the record actually fills, which
    is what a write of the same record already costs
    (:func:`sm_records.services._claims.ensure_unique`). It is asked on the
    single-record read only — a list turns the badge off wholesale
    (``contracts.schemas.record_list_read``), which is also what keeps this
    off the page-sized path.
    """
    defs = field_defs(rtype)
    values = from_stored(defs, dict(record.data or {}))
    out: list[dict[str, str]] = []
    for field in defs:
        if not field.unique:
            continue
        value = values.get(field.key)
        if value is None:
            continue
        if await _claims.taken_by(
            db,
            rtype,
            field,
            value,
            exclude_id=record.id,
            exclude_group=record.translation_group,
        ):
            out.append(_error(field.key, value))
    return out
