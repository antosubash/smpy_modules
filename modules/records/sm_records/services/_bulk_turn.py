"""One record's turn through a bulk pass — a single-record call and nothing else.

Split from :mod:`sm_records.services.bulk` for the 300-line cap, along the
seam that module's docstring already draws in prose: ``apply_bulk`` owns *the
pass* — the type lock, the per-record savepoint, the collected refusals and
the all-or-nothing rollback — and everything here is one record inside it.
Nothing is re-implemented on either side of the seam; a turn is a call into
:mod:`sm_records.services.records` plus what the pass needs back from it.

:class:`Change` is that "what the pass needs back", and it is re-exported from
``bulk`` so no caller has to learn this module exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.bulk import BulkAction
from sm_records.models import Record, RecordStatus, RecordType
from sm_records.services import records as record_service
from sm_records.services._empty_trash import Identity
from sm_records.services.errors import Conflict
from sm_records.settings import RecordsSettings

__all__ = ["Change", "apply_one", "check_version"]


@dataclass(slots=True)
class Change:
    """What one record's turn through :func:`apply_bulk` actually did.

    Deliberately event-shaped without being an event: the services layer does
    not know about the bus (``docs/architecture.md`` rule 1), so it hands back
    the three things :mod:`sm_records.events` needs to build one and the
    endpoint chooses the builder from the action it asked for.

    ``record`` is the ORM row — except for a purge, where it is the identity
    read before the row was removed, since afterwards there is nothing to read
    it from. ``cascade`` is what ``soft_delete_record`` returned, every
    ``(record, type)`` pair a trash reached; ``status_before`` is the status a
    publish or unpublish moved away from.

    ``unchanged`` marks the turn that did nothing because there was nothing to
    do — a publish of a published record. It is still a :class:`Change`, and
    deliberately: the pass has to report it, and the alternative (returning
    ``None``) would make every caller of this module handle an absence where
    the record is perfectly fine.
    """

    record: Any
    cascade: list[tuple[Record, RecordType]] = field(default_factory=list)
    status_before: str | None = None
    unchanged: bool = False


def check_version(record: Record, expected: int | None) -> None:
    """The optimistic-concurrency check for the turns that do not bump.

    A ``publish``/``unpublish`` that moves a record goes through
    ``update_record``, which makes this check as a guarded ``UPDATE`` and
    bumps the version with it. Trash, restore and purge change a record's
    *existence* and leave its version alone, and a publish that finds nothing
    to do writes nothing at all, so for those the check is explicit — and
    still worth making: a selection taken from a list someone else has edited
    since is exactly the situation ``expected_version`` exists for, and a
    record being already published says nothing about whether the operator was
    looking at the current row.
    """
    if expected is not None and record.version != expected:
        raise Conflict(f"record {record.uuid} has changed since it was read")


def _attributed(
    cascade: Sequence[tuple[Record, RecordType]],
    rtype: RecordType,
    record: Record,
    named: frozenset[str],
) -> list[tuple[Record, RecordType]]:
    """``cascade`` without the records this batch also names in their own right.

    Each of those has a turn of its own and publishes its own
    ``RecordTrashed`` with ``cascaded_from`` unset — the caller did name it —
    so left in here one record would publish two events and count as
    ``changed`` and as ``cascaded`` both. Matched on the type's id as well as
    the uuid: a uuid is unique within a table set, not across them (Phase 5
    §6.3), and ``named`` lists records of *this* type.
    """
    return [
        (doomed, its_type)
        for doomed, its_type in cascade
        if doomed.uuid == record.uuid or not (its_type.id == rtype.id and doomed.uuid in named)
    ]


async def apply_one(
    db: AsyncSession,
    rtype: RecordType,
    uuid: str,
    *,
    action: BulkAction,
    expected: int | None,
    settings: RecordsSettings,
    actor: str | None,
    roles: Sequence[str] | None,
    named: frozenset[str],
    trashed: set[str],
) -> Change:
    """One record's turn — the single-record service call and nothing else.

    ``named`` is every uuid the request listed, ``trashed`` every uuid the pass
    has already put in the trash, cascades included — together, what keeps a
    self-relation from being an order-dependent refusal. A cascade into the
    *same* type (a category tree, a threaded type) reaches records a list
    screen may well have selected too, and by their own turn they are gone, so
    ``get_record`` would refuse them — and the batch with them — for a removal
    the batch itself performed. Such a turn counts as changed. A record
    trashed *before* the request is still a refusal, as on the single-record
    endpoint: there the caller is acting on a state they never read.
    """
    if action is BulkAction.TRASH:
        if uuid in trashed:
            already = await record_service.get_deleted_record(db, rtype, uuid)
            check_version(already, expected)
            return Change(already, cascade=[(already, rtype)])
        record = await record_service.get_record(db, rtype, uuid)
        check_version(record, expected)
        cascade = await record_service.soft_delete_record(
            db, rtype, record, actor=actor, settings=settings, roles=roles
        )
        trashed.update(doomed.uuid for doomed, its_type in cascade if its_type.id == rtype.id)
        return Change(record, cascade=_attributed(cascade, rtype, record, named))
    if action is BulkAction.RESTORE:
        record = await record_service.get_deleted_record(db, rtype, uuid)
        check_version(record, expected)
        restored = await record_service.restore_record(
            db, rtype, record, settings=settings, actor=actor
        )
        return Change(restored)
    if action is BulkAction.PURGE:
        record = await record_service.get_deleted_record(db, rtype, uuid)
        check_version(record, expected)
        # Read before the purge, for the reason the single-record endpoint
        # builds its event before calling: afterwards the row is expunged and
        # the uuid it names is the one thing a subscriber cannot look up.
        identity = Identity(record.uuid, record.locale, record.translation_group)
        await record_service.hard_delete_record(db, rtype, record)
        return Change(identity)
    record = await record_service.get_record(db, rtype, uuid)
    was = record.status.value
    status = RecordStatus.PUBLISHED if action is BulkAction.PUBLISH else RecordStatus.DRAFT
    if record.status is status:
        # Already there, so there is nothing to apply — and applying it anyway
        # is not free. The write below bumps ``version``, snapshots an
        # ``update`` revision and publishes a ``RecordUpdated`` for a record
        # whose status and payload are exactly what they were, so the natural
        # gesture (tick the header box, press Publish) churns the history of
        # every record that was already published. Counted apart from
        # ``changed`` rather than folded into it: "12 records published" about
        # nine that moved is a number the operator cannot reconcile with the
        # list in front of them.
        check_version(record, expected)
        return Change(record, status_before=was, unchanged=True)
    # The record's own payload, read the way the editor reads it (§8.3's
    # lenient read) and written straight back: a status change through
    # ``update_record`` is the same write the editor makes when it flips the
    # toggle and saves, restamp at the current schema version included. A
    # payload the current schema no longer accepts is therefore a 422 here
    # too — which is honest, and which the report names rather than hides.
    view = record_service.read_view(rtype, record, with_invalid=False)
    updated = await record_service.update_record(
        db,
        rtype,
        record,
        expected_version=expected if expected is not None else record.version,
        data=view["data"],
        settings=settings,
        status=status,
        # The row's own slug, not ``None``: ``None`` means "derive from the
        # slug field", and a record whose slug was set by hand would quietly
        # have it rewritten by an action that is supposed to change one thing.
        slug=record.slug,
        actor=actor,
    )
    return Change(updated, status_before=was)
