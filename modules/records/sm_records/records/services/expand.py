"""``?expand=`` — resolving what a relation field points at (design §9, #81).

The forward half of relations, and the one the API makes opt-in: a read
returns the stored ``{"type": ..., "uuid": ...}`` untouched unless the caller
names the field, at which point this resolves it — and, for a dotted path
such as ``author.publisher``, resolves the resolved target's field in turn,
up to ``max_expand_depth`` levels.

Five rules, all of them load-bearing:

* **One batched statement per hop, for the whole page, at every level.** The
  list screen expands every relation column it renders (§9), so a per-row
  lookup would make a page of fifty records fifty queries per column — and a
  per-*target* lookup one level down would multiply that again. Every uuid a
  hop holds across every record its level reached is collected first and
  read in one ``IN``; a row an earlier hop already read is not read again.
* **A cycle ends the walk, the depth cap ends it anyway.** A user-defined
  graph has cycles. A target that is already on its own chain — the record
  being read, or one an outer level expanded — comes back resolved and
  flagged ``cycle``, and is not expanded again. Paths are explicit and capped
  (``_expand_grammar``), so the walk would terminate regardless; the flag is
  what keeps a cycle from padding the response with copies of itself.
* **A missing target is flagged, never fatal.** Trashed and purged both read
  back as ``dangling`` (:func:`~sm_records.contracts.relations.expanded_ref`),
  because §9 says a restorable delete must not break what references it. The
  lookup runs with ``include_deleted`` so a trashed row is *found* and marked
  by this pass — a second query to tell "trashed" from "purged" apart would be
  a query per read to produce the same word. So do the two things a payload
  can hold that are not a resolvable reference: an entry that is not a
  ``{"type", "uuid"}`` object at all, and one whose uuid is not a record of
  the *declared* target type. Both keep their slot (:func:`_refs`), because
  a to-many expansion is rendered positionally against ``data``. A field
  holding *nothing* — ``None``, or an empty list — is not one of them and
  expands to no entries at all.
* **A target the caller may not see is ``restricted``, decided from the
  field's declared ``target_type`` alone, at every level.** Nothing about the
  row is read, so a restricted expansion leaks neither its content nor
  whether the uuid still exists — nor, one level down, anything its own
  relations hold (:mod:`._expand_plan` plans nothing beneath it). The
  predicate is ``_access.role_blocked`` — the same one
  ``deps.check_type_roles`` raises on, so the read surface cannot be more
  permissive than the write surface. Every statement runs on the request's
  session, so the tenant binding that scopes the page scopes every hop.
* **Work past depth one is budgeted.** ``max_refs`` bounds the references
  resolved below depth one, summed over the levels; a level that would cross
  it is refused *before* it is read, naming its path.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.relations import ExpandedRef, expanded_ref
from sm_records.models import Record, RecordType, tables_for
from sm_records.records.index.query import QueryError
from sm_records.records.services._expand_plan import Hop, plan
from sm_records.records.services._expand_refs import _live, _refs, relation_field_keys

__all__ = ["ExpandedMap", "expand", "relation_field_keys"]

ExpandedMap = dict[str, dict[str, list[ExpandedRef]]]
"""``{record uuid: {field key: [ExpandedRef, ...]}}`` — what fills
``RecordRead.expanded``. Keyed by uuid and not by row id because that is the
identifier the contract, the payload and the URL all speak."""

_Holder = tuple[Record, dict[str, list[ExpandedRef]], frozenset[tuple[int, str]]]
"""A record a level reads relations *of*: the row, the dict its expansion is
written into, and the ``(type id, uuid)`` of every record on its chain (itself
included) — the cycle set. Keyed like ``_Rows`` and not by uuid alone: each
collection has its own record table, so two distinct records of two types can
share a uuid, and a relation from one to the other is not a cycle."""

_Rows = dict[tuple[int, str], Record]
"""Every row this request has read, by ``(type id, uuid)``."""


async def _targets(
    db: AsyncSession, target_type: RecordType, uuids: set[str], rows: _Rows
) -> dict[str, Record]:
    """Every target of one hop, in one ``IN`` — less what ``rows`` holds.

    **The target type decides the table** (Phase 5 §6.3): a relation from a
    collection type to a global one reads the global record table and back the
    other way reads the collection's, and either way it is still one batched
    query per hop. The type is a resolved row here rather than an id because
    the row is what carries ``collection``.

    ``include_deleted``: see the module docstring — a trashed target has to be
    *found* here, or telling it from a purged one costs a second query per
    read to produce the same ``dangling`` either way.

    ``type_id`` is the **declared** target type's, and it is a predicate and
    not a filter applied afterwards: ``restricted`` is decided from the
    declared target alone, so a row found under any *other* type would carry
    a decision that was never made about it — which is how a stored ref
    saying ``{"type": "secret", ...}`` on a field declared ``author`` came
    back with the secret record's title and ``restricted: false``. A uuid
    that is not a record of the declared type is simply not found, and reads
    as ``dangling`` like every other unresolvable reference (§9). ``rows`` is
    keyed by the same type id, so a row read under one type is never handed
    to a hop declaring another.
    """
    unread = sorted(uuid for uuid in uuids if (target_type.id, uuid) not in rows)
    if unread:
        cls = tables_for(target_type).record
        stmt = (
            select(cls)
            .where(cls.uuid.in_(unread), cls.type_id == target_type.id)
            .execution_options(include_deleted=True)
        )
        for row in (await db.execute(stmt)).scalars().all():
            rows[(target_type.id, row.uuid)] = row
    return {uuid: rows[(target_type.id, uuid)] for uuid in uuids if (target_type.id, uuid) in rows}


_Refs = list[list[tuple[str, str, bool]]]
""":func:`_refs` of one hop, per holder — computed once, charged and resolved."""


async def _resolve_hop(
    db: AsyncSession, key: str, hop: Hop, holders: list[_Holder], per_holder: _Refs, rows: _Rows
) -> list[_Holder]:
    """Write ``hop``'s references into every holder; return the next level's.

    A hop with no declared target type (it names a type that no longer
    exists) reads nothing: nothing can be resolved *as* it — the same answer
    the type predicate in ``_targets`` gives for a mismatch.
    """
    wanted = {uuid for refs in per_holder for _, uuid, ok in refs if ok}
    found = (
        {} if hop.restricted or hop.target is None else await _targets(db, hop.target, wanted, rows)
    )
    below: list[_Holder] = []
    for (_, out, chain), refs in zip(holders, per_holder, strict=True):
        entries = []
        for type_key, uuid, resolvable in refs:
            target = _live(found.get(uuid)) if resolvable else None
            cycle = target is not None and (target.type_id, target.uuid) in chain
            ref = expanded_ref(type_key, uuid, target, restricted=hop.restricted, cycle=cycle)
            if hop.children and target is not None and not hop.restricted and not cycle:
                ref.expanded = {}
                below.append((target, ref.expanded, chain | {(target.type_id, target.uuid)}))
            entries.append(ref)
        out[key] = entries
    return below


def _charge(hop: Hop, per_holder: _Refs, spent: int, budget: int | None) -> int:
    """Count the references a deeper level is about to resolve, against the
    budget, and refuse the request before the level is read if it crosses.

    A hop that reads nothing (restricted, or its target type is gone) resolves
    no references, so it is not charged for them."""
    if hop.restricted or hop.target is None:
        return spent
    spent += sum(len(refs) for refs in per_holder)
    if budget is not None and spent > budget:
        raise QueryError(
            hop.path,
            "expand_budget",
            f"expanding {hop.path!r} would resolve more than {budget} references "
            "below depth one; expand fewer paths or read a smaller page",
        )
    return spent


async def expand(
    db: AsyncSession,
    rtype: RecordType,
    records: Sequence[Record],
    paths: Sequence[str],
    *,
    roles: Sequence[str] | None = None,
    max_refs: int | None = None,
) -> ExpandedMap:
    """Resolve ``paths`` (field keys, or dotted paths of them) for every
    record in ``records``.

    ``roles`` is the caller's role list (``deps.caller_roles``); ``None`` means
    no caller at all — a CLI or background path — and resolves everything, the
    same reading ``role_blocked`` gives it everywhere else. ``max_refs`` is
    the below-depth-one budget; ``None`` leaves it unbounded.

    Statement count is ``(levels) + (hops actually read)``: one per level for
    the target types it introduces, one per hop that has a uuid not already
    read. A hop whose target type this caller may not see is not read at all,
    so it costs nothing and reveals nothing. Depth one alone is therefore the
    ``1 + fields`` it always was.
    """
    hops = await plan(db, rtype, paths, roles)
    out: ExpandedMap = {record.uuid: {} for record in records}
    if not hops or not records:
        return out
    rows: _Rows = {}
    spent = 0
    level: list[tuple[dict[str, Hop], list[_Holder]]] = [
        (
            hops,
            [
                (record, out[record.uuid], frozenset({(record.type_id, record.uuid)}))
                for record in records
            ],
        )
    ]
    depth = 1
    while level:
        next_level = []
        for level_hops, holders in level:
            for key, hop in level_hops.items():
                per_holder = [_refs(record, key, hop.target_key) for record, _, _ in holders]
                if depth > 1:
                    spent = _charge(hop, per_holder, spent, max_refs)
                below = await _resolve_hop(db, key, hop, holders, per_holder, rows)
                if hop.children and below:
                    next_level.append((hop.children, below))
        level = next_level
        depth += 1
    return out
