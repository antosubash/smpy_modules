"""Planning a delete: who points at the record, and what that costs them.

Split out of :mod:`sm_records.services._lifecycle` for the 300-line cap, along
the seam design §9 already draws. That module is about a record's own
existence — trash it, restore it, purge it. This one is about *everybody
else's*: the breadth-first walk over the referrer graph that decides whether a
delete is refused, and the rewrite of a referring record whose field says
``set_null``.

**Both halves cross collections** (Phase 5 §6.4). A ``relation`` names its
target by ``(type, uuid)`` and nothing about that says the referrer lives in
the same table set, so the walk may reach a global record from a collection
one and back again; the referrer query resolves each referrer's own type and
takes its tables from that.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.reduce import snapshot
from sm_records.index.writer import write_index
from sm_records.models import Record, RecordType, RevisionEvent, tables_for
from sm_records.services import _payload, _relations
from sm_records.services._common import guarded_bump, reload, role_blocked, type_resolver
from sm_records.services.errors import Conflict
from sm_records.services.revisions import write_revision
from sm_records.settings import RecordsSettings

__all__ = ["BLOCKER_CAP", "Blockers", "apply_set_null", "plan_delete"]

BLOCKER_CAP: Final = 50
"""How many blocker uuids a refusal lists. The same reasoning as
``contracts.io.ERROR_CAP``: a type whose records were loaded in bulk can have
a hundred thousand referrers, and a 409 body of a hundred thousand uuids is a
response nobody reads and a payload larger than the record it is about. The
count stays exact — ``Blockers.more`` says how many are not listed."""


@dataclass(slots=True)
class Blockers:
    """Why a delete is refused, split by what the caller may be told.

    ``listed`` names blockers the caller can read for themselves; ``hidden``
    only *counts* the ones whose type narrows ``allowed_roles`` past them,
    because naming those is the leak the referrers panel exists not to be
    (``contracts.relations``: the count is honest, *which* records they are
    does not travel). ``more`` is visible blockers past :data:`BLOCKER_CAP`.

    ``total`` is all three, and it is the number the refusal's ``detail``
    speaks — the panel's ``total`` and the delete dialog say the same one.
    """

    listed: list[str] = field(default_factory=list)
    hidden: int = 0
    more: int = 0

    @property
    def total(self) -> int:
        return len(self.listed) + self.hidden + self.more

    def __bool__(self) -> bool:
        return self.total > 0

    def add(self, uuid: str, *, blocked: bool) -> None:
        if blocked:
            self.hidden += 1
        elif len(self.listed) < BLOCKER_CAP:
            self.listed.append(uuid)
        else:
            self.more += 1


_RESTRICT = "restrict"
_SET_NULL = "set_null"
_CASCADE = "cascade"


async def apply_set_null(
    db: AsyncSession,
    ref: _relations.Referrer,
    uuid: str,
    *,
    actor: str | None,
    settings: RecordsSettings,
) -> None:
    """Drop the reference, then rewrite the referrer as any other edit would.

    A to-many field loses only the entry that pointed at the deleted record;
    a to-one field goes to ``None``. Nulling the whole list would delete
    references to records nobody asked to delete, which is the mistake
    ``restrict``-by-default exists to avoid one level up.

    The rewrite goes through the same bump-and-revise path
    :func:`~sm_records.services.records.update_record` uses, and not a bare
    ``data`` assignment: this *is* an edit of somebody else's record. Without
    the version bump a client holding the pre-delete version writes straight
    over it under optimistic concurrency that reports no conflict; without the
    revision the change is absent from the history panel that is supposed to
    explain where the reference went; and without recomputing
    ``display_title`` a type whose ``display_field`` *is* the relation keeps a
    list-screen title naming a record that is now in the trash.
    """
    previous_data = dict(ref.record.data or {})
    data = dict(previous_data)
    value = data.get(ref.field_key)
    if isinstance(value, list):
        kept = [item for item in value if not (isinstance(item, dict) and item.get("uuid") == uuid)]
        data[ref.field_key] = kept or None
    else:
        data[ref.field_key] = None

    expected = ref.record.version
    # The referrer's own class, which may be a different collection's from the
    # record being deleted (Phase 5 §6.4): ``on_delete`` crosses collections.
    referrer_cls = tables_for(ref.rtype).record
    if not await guarded_bump(db, referrer_cls, ref.record.id, expected):
        raise Conflict(
            f"record {ref.record.uuid} has changed since it was read",
            current=await reload(db, referrer_cls, ref.record.id),
        )
    ref.record.data = data
    ref.record.version = expected + 1
    ref.record.updated_by = actor
    # The stored payload, not a revalidated one: the referrer may be stamped at
    # an older ``schema_version`` than its type now carries (§8.3), and a
    # delete elsewhere is not the event that gets to refuse it.
    ref.record.display_title = _payload.display_title(ref.rtype, data)
    db.add(ref.record)
    await db.flush()
    await write_revision(
        db, ref.record, RevisionEvent.UPDATE, limit=settings.revision_limit, actor=actor
    )
    # ``previous``: an ordinary edit of somebody else's record, so a reduce
    # index moves it off the group its old payload put it in (Phase 5 §5.2).
    await write_index(
        db,
        ref.record,
        ref.rtype,
        resolve_type_id=await type_resolver(db),
        previous=snapshot(ref.record, previous_data),
    )


async def plan_delete(
    db: AsyncSession, rtype: RecordType, record: Record, roles: Sequence[str] | None
) -> tuple[list[tuple[Record, RecordType]], list[tuple[_relations.Referrer, str]], Blockers]:
    """Walk the whole referrer graph without touching a row.

    Returns ``(records to trash, set_null rewrites, blockers)`` — see
    :class:`Blockers` for why the last is not simply a list of uuids. The
    walk is breadth-first with a visited set, because a user-defined graph can
    hold a cycle — two types each relating to the other — and without the set
    the first such cycle is a ``RecursionError`` in a delete handler.
    """
    trash: list[tuple[Record, RecordType]] = [(record, rtype)]
    set_nulls: list[tuple[_relations.Referrer, str]] = []
    blockers = Blockers()
    seen_blockers: set[str] = set()
    # Keyed by ``(collection, id)`` and not by ``id`` alone: two records in two
    # collections can share a primary key, and a visited set that could not tell
    # them apart would drop one of them from the cascade (Phase 5 §6.4).
    visited: set[tuple[str | None, int]] = {(rtype.collection, record.id)}
    queue: list[Record] = [record]

    while queue:
        current = queue.pop(0)
        for ref in await _relations.referrers(db, current):
            behaviour = ref.on_delete
            # ``role_blocked`` and not a local copy: design §10's narrowing has
            # to reach a type the URL never names — a cascade or a set_null into
            # a *different* type would otherwise trash or rewrite records this
            # caller may not write at all. Same predicate as the read paths.
            blocked = role_blocked(ref.rtype, roles)
            if behaviour != _RESTRICT and blocked:
                behaviour = _RESTRICT
            if behaviour == _RESTRICT:
                if ref.record.uuid not in seen_blockers:
                    seen_blockers.add(ref.record.uuid)
                    # ``blocked`` decides whether the uuid travels, not what
                    # made this a blocker: a declared ``restrict`` in a type
                    # the caller may not read is as unnameable as a cascade
                    # that was downgraded into one.
                    blockers.add(ref.record.uuid, blocked=blocked)
            elif behaviour == _SET_NULL:
                set_nulls.append((ref, current.uuid))
            elif behaviour == _CASCADE and (ref.rtype.collection, ref.record.id) not in visited:
                visited.add((ref.rtype.collection, ref.record.id))
                trash.append((ref.record, ref.rtype))
                queue.append(ref.record)
    return trash, set_nulls, blockers
