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

One record's *turn* is :mod:`sm_records.services._bulk_turn`, split off for
the file cap along the line this docstring already draws: the pass is here,
what happens inside one iteration of it is there, and :class:`Change` is
re-exported so callers still import one module.

:func:`empty_trash` does the opposite and is re-exported from
:mod:`sm_records.services._empty_trash`: it names no records, so it is one
statement per table over a set of them rather than a pass over each.

Nothing here commits, like everything else in this layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.bulk import BulkAction, BulkFailure, BulkReport, BulkResult
from sm_records.models import RecordType

# Re-exported: one record's turn is the same single-record call the endpoint
# would have made, and lives next door for the file cap — see that module.
from sm_records.services._bulk_turn import Change, apply_one
from sm_records.services._claims import lock_type

# Re-exported: emptying the trash is one statement per table over a set of
# records rather than a pass over them one at a time, and lives in
# ``_empty_trash`` for that reason and for the file cap. Callers still import
# one module.
from sm_records.services._empty_trash import Identity, empty_trash
from sm_records.services.errors import BulkRefused, RecordsError, ReferencedByOthers
from sm_records.settings import RecordsSettings

__all__ = ["Change", "Identity", "apply_bulk", "empty_trash"]


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


def _failure(uuid: str, exc: RecordsError) -> BulkFailure:
    """One refused record, with the structured half of the refusal kept.

    A ``restrict`` blocker is the one refusal whose 409 carries more than a
    sentence, and flattening it to ``message`` was what left the panel with a
    uuid and nothing to render. The four keys are the single-record body's,
    unchanged, so a client has one shape to read either way.
    """
    if isinstance(exc, ReferencedByOthers):
        return BulkFailure(
            uuid=uuid,
            status=exc.status_code,
            message=exc.detail,
            total=exc.total,
            referrers=exc.referrers,
            hidden=exc.hidden,
            more=exc.more,
        )
    return BulkFailure(uuid=uuid, status=exc.status_code, message=exc.detail)


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
    # What a later turn needs to know about the earlier ones — see
    # ``_bulk_turn.apply_one``. A failed turn adds nothing: it raises first.
    named = frozenset(wanted)
    trashed: set[str] = set()
    # Before the first savepoint, and load-bearing twice over — see the module
    # docstring's third paragraph.
    await lock_type(db, rtype)
    for uuid in wanted:
        try:
            # See the module docstring: the savepoint is what lets the pass
            # continue after a refusal so the report can name all of them.
            async with db.begin_nested():
                changes.append(
                    await apply_one(
                        db,
                        rtype,
                        uuid,
                        action=action,
                        expected=versions.get(uuid),
                        settings=settings,
                        actor=actor,
                        roles=roles,
                        named=named,
                        trashed=trashed,
                    )
                )
        except RecordsError as exc:
            failures.append(_failure(uuid, exc))
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
    # Every pair but the record's own, and ``_bulk_turn`` already took the
    # named ones out — so nothing counts as changed *and* cascaded.
    cascaded = sum(max(len(change.cascade) - 1, 0) for change in changes)
    # A turn that found nothing to do is not a refusal and not a change; see
    # ``_bulk_turn.apply_one``. ``requested`` still equals ``changed +
    # unchanged``, because a batch with a refusal in it answers no result.
    unchanged = sum(1 for change in changes if change.unchanged)
    return (
        BulkResult(
            action=action,
            requested=len(wanted),
            changed=len(changes) - unchanged,
            unchanged=unchanged,
            cascaded=cascaded,
        ),
        changes,
    )
