"""Applying one action to many records, and emptying the trash.

Two functions, one rule each.

:func:`apply_bulk` **composes, it does not reimplement.** Every record it
names goes through the same ``services.records`` call the single-record
endpoint makes, so ``allowed_roles``, the ``on_delete`` cascade, the unique
and slug claims, the revision log and the index writes all behave exactly as
they do for one record — there is no second code path that can drift from the
first. What is new here is only the *confirmation semantics*: the pass
continues past a refusal so every one of them can be reported, and then the
whole batch is refused with nothing written.

Each record's turn runs inside a savepoint, for the reason
``services.import_`` opens one per row: a refused write leaves the session
needing a rollback, and rolling the outer transaction back at the first
refusal would end the pass with one failure named out of five. The savepoint
rolls back that record's attempt and the pass goes on collecting. When it is
over and anything failed, :class:`~sm_records.services.errors.BulkRefused`
takes the *outer* transaction with it (``RecordsErrorRoute`` rolls it back),
which is what makes all-or-nothing true rather than aspirational.

**The type is locked before the loop, and on SQLite that is what makes the
sentence above true at all.** The semantic reason comes first: a write over
many records of a type should serialise against schema changes and against
other writers exactly as every single-record write does, and those take the
lock inside ``_prepare`` — a path ``trash``/``restore``/``purge`` never touch.
The mechanical reason is pysqlite's legacy transaction control, which emits
``BEGIN`` only before the first DML statement it recognises. With no write
ahead of it the batch's first statement is ``SAVEPOINT``, which SQLite then
treats as the start of the transaction and whose ``RELEASE`` *commits* — so
the outer rollback at the end had nothing left to undo and a refused batch
left its earlier records trashed. ``lock_type`` issues an ``UPDATE`` on
SQLite (a ``SELECT … FOR UPDATE`` on Postgres, where savepoints are real
either way), so the savepoints nest inside a transaction that exists.

:func:`empty_trash` does the opposite and is re-exported from
:mod:`sm_records.services._empty_trash`: it names no records, so it is one
statement per table over a set of them rather than a pass over each.

Nothing here commits, like everything else in this layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.bulk import BulkAction, BulkFailure, BulkReport, BulkResult
from sm_records.models import Record, RecordStatus, RecordType
from sm_records.services import records as record_service
from sm_records.services._claims import lock_type

# Re-exported: emptying the trash is one statement per table over a set of
# records rather than a pass over them one at a time, and lives in
# ``_empty_trash`` for that reason and for the file cap. Callers still import
# one module.
from sm_records.services._empty_trash import Identity, empty_trash
from sm_records.services.errors import BulkRefused, Conflict, RecordsError
from sm_records.settings import RecordsSettings

__all__ = ["Change", "Identity", "apply_bulk", "empty_trash"]


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
    """

    record: Any
    cascade: list[tuple[Record, RecordType]] = field(default_factory=list)
    status_before: str | None = None


def _distinct(uuids: Iterable[str]) -> list[str]:
    """``uuids`` with repeats collapsed, first occurrence winning.

    A selection model that sends the same record twice means it once. Left in,
    the second turn would refuse ("already in the trash") and take the whole
    batch down with it — a refusal about the request's shape wearing the
    clothes of one about the data.
    """
    seen: set[str] = set()
    out: list[str] = []
    for uuid in uuids:
        if uuid not in seen:
            seen.add(uuid)
            out.append(uuid)
    return out


def _check_version(record: Record, expected: int | None) -> None:
    """The optimistic-concurrency check for the three actions that do not bump.

    ``publish``/``unpublish`` go through ``update_record``, which makes this
    check as a guarded ``UPDATE`` and bumps the version with it. Trash,
    restore and purge change a record's *existence* and leave its version
    alone, so the check is explicit — and still worth making: a selection
    taken from a list someone else has edited since is exactly the situation
    ``expected_version`` exists for.
    """
    if expected is not None and record.version != expected:
        raise Conflict(f"record {record.uuid} has changed since it was read")


async def _apply_one(
    db: AsyncSession,
    rtype: RecordType,
    uuid: str,
    *,
    action: BulkAction,
    expected: int | None,
    settings: RecordsSettings,
    actor: str | None,
    roles: Sequence[str] | None,
) -> Change:
    """One record's turn — the single-record service call and nothing else."""
    if action is BulkAction.TRASH:
        record = await record_service.get_record(db, rtype, uuid)
        _check_version(record, expected)
        cascade = await record_service.soft_delete_record(
            db, rtype, record, actor=actor, settings=settings, roles=roles
        )
        return Change(record, cascade=list(cascade))
    if action is BulkAction.RESTORE:
        record = await record_service.get_deleted_record(db, rtype, uuid)
        _check_version(record, expected)
        restored = await record_service.restore_record(
            db, rtype, record, settings=settings, actor=actor
        )
        return Change(restored)
    if action is BulkAction.PURGE:
        record = await record_service.get_deleted_record(db, rtype, uuid)
        _check_version(record, expected)
        # Read before the purge, for the reason the single-record endpoint
        # builds its event before calling: afterwards the row is expunged and
        # the uuid it names is the one thing a subscriber cannot look up.
        identity = Identity(record.uuid, record.locale, record.translation_group)
        await record_service.hard_delete_record(db, rtype, record)
        return Change(identity)
    record = await record_service.get_record(db, rtype, uuid)
    was = record.status.value
    status = RecordStatus.PUBLISHED if action is BulkAction.PUBLISH else RecordStatus.DRAFT
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


async def apply_bulk(
    db: AsyncSession,
    rtype: RecordType,
    *,
    action: BulkAction,
    uuids: Sequence[str],
    expected_versions: dict[str, int] | None = None,
    settings: RecordsSettings,
    actor: str | None = None,
    roles: Sequence[str] | None = None,
) -> tuple[BulkResult, list[Change]]:
    """Apply ``action`` to every record in ``uuids``, or to none of them.

    Returns the result and one :class:`Change` per record, in the order the
    caller named them, for the endpoint to publish events from. Raises
    :class:`~sm_records.services.errors.BulkRefused` — with a report naming
    every uuid that refused and why — if any of them did.

    ``roles`` is the caller's role list and ``None`` means unrestricted,
    exactly as in ``soft_delete_record``: it is what makes a cascade into a
    type the caller may not write refuse this batch rather than rewrite data
    the request never mentioned.
    """
    wanted = _distinct(uuids)
    versions = expected_versions or {}
    changes: list[Change] = []
    failures: list[BulkFailure] = []
    # Before the first savepoint, and load-bearing twice over — see the module
    # docstring's third paragraph.
    await lock_type(db, rtype)
    for uuid in wanted:
        try:
            # See the module docstring: the savepoint is what lets the pass
            # continue after a refusal so the report can name all of them.
            async with db.begin_nested():
                changes.append(
                    await _apply_one(
                        db,
                        rtype,
                        uuid,
                        action=action,
                        expected=versions.get(uuid),
                        settings=settings,
                        actor=actor,
                        roles=roles,
                    )
                )
        except RecordsError as exc:
            failures.append(BulkFailure(uuid=uuid, status=exc.status_code, message=exc.detail))
            # Rolling the savepoint back expires whatever the refused record's
            # attempt touched inside it — on SQLite that includes the type row,
            # which ``_prepare``'s own ``lock_type`` writes to. Reload it here,
            # inside the greenlet, rather than leave the next record's turn (or
            # the endpoint's event, which reads ``rtype.key``) to a lazy load
            # that has none. ``services.import_`` does the same after its own
            # per-row savepoint, for the same reason.
            if inspect(rtype).expired_attributes:
                await db.refresh(rtype)
    if failures:
        raise BulkRefused(
            BulkReport(action=action, requested=len(wanted), failed=failures),
            f"{len(failures)} of {len(wanted)} record(s) refused {action.value}; "
            "nothing was changed",
        )
    cascaded = sum(max(len(change.cascade) - 1, 0) for change in changes)
    return (
        BulkResult(action=action, requested=len(wanted), changed=len(changes), cascaded=cascaded),
        changes,
    )
