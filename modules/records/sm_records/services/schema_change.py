"""Changing a populated type's schema — the whole of design doc §8, applied.

Three entry points, one pipeline:

* :func:`preview` classifies a proposed ``fields`` list and reports what it
  would do to the records that exist. It writes nothing and is the endpoint a
  UI calls while the operator is still editing.
* :func:`apply` re-runs that classification *inline* and then writes. It
  re-runs rather than trusting a report id, because a report is taken against
  records that may have changed since (§8.9) — persisting one would mean
  trusting a snapshot of a different database.
* :func:`rollback` writes an earlier :class:`RecordTypeRevision` back through
  :func:`apply`, so an undo is classified like any other change (§8.6) and a
  rollback that would invalidate records is refused like any other change.

**The payload never migrates here.** A restrictive change that is applied with
``force`` leaves the failing rows exactly as they were: they are *marked*, not
mutated and not hidden (§8.3 — ``services.records.read_view`` reports them
under ``invalid``). The only rows this module ever rewrites are the reserved
``_orphaned`` sub-key on an explicit ``discard``, and the index, which is
derived and therefore rebuilt out of request (§8.5, :mod:`reindex_runner`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import REINDEX_ALL
from sm_records.index.reindex import pending_map
from sm_records.models import RecordType, RecordTypeRevision
from sm_records.schema.changes import DryRunReport, SchemaDiff
from sm_records.schema.diff import diff_fields
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import ChangeClass
from sm_records.services import _orphaned
from sm_records.services._common import guarded_bump, reload, utcnow
from sm_records.services._dry_run import dry_run
from sm_records.services._payload import field_defs, lock_type
from sm_records.services._schema import check_pointers, check_targets, normalise, snapshot
from sm_records.services.errors import (
    Conflict,
    NotFound,
    OrphanedKeyConflict,
    SchemaChangeRefused,
)
from sm_records.settings import RecordsSettings

__all__ = ["apply", "preview", "rollback"]

_POINTERS = ("display_field", "slug_field")


def _added_keys(diff: SchemaDiff) -> list[str]:
    return [c.field_key for c in diff.changes if c.what == "field_added"]


def _needs_dry_run(diff: SchemaDiff) -> bool:
    """Only a restrictive change can invalidate a record. An additive or
    index-affecting one cannot, by construction, and a destructive one takes
    the field away rather than the rows — so scanning the type for them would
    be a full pass that can only ever report zero (§8.2). A type change is
    already classified restrictive, so it is covered here."""
    return any(c.kind is ChangeClass.RESTRICTIVE for c in diff.changes)


async def _report(
    db: AsyncSession,
    rtype: RecordType,
    new_defs: list[FieldDefinition],
    settings: RecordsSettings,
    *,
    diff: SchemaDiff,
    conflicts: dict[str, int],
    drop_keys: frozenset[str] = frozenset(),
) -> DryRunReport:
    if not _needs_dry_run(diff):
        return DryRunReport(checked=0, failing=0, orphaned_conflicts=conflicts)
    return await dry_run(
        db,
        rtype,
        new_defs,
        batch_size=settings.reindex_batch_size,
        orphaned_conflicts=conflicts,
        drop_keys=drop_keys,
    )


async def preview(
    db: AsyncSession,
    rtype: RecordType,
    fields_raw: list[dict[str, Any]],
    settings: RecordsSettings,
) -> tuple[SchemaDiff, DryRunReport]:
    """Classify a proposed ``fields`` list and dry-run it. Writes nothing.

    ``checked`` is ``0`` for a change that cannot invalidate anything — see
    :func:`_needs_dry_run`. ``orphaned_conflicts`` is always computed, because
    it is about which *keys* exist rather than about whether they validate, and
    it is what §8.8 refuses on.
    """
    new_defs, _ = normalise(fields_raw, settings)
    diff = diff_fields(field_defs(rtype), new_defs)
    conflicts = await _orphaned.count_conflicts(
        db, rtype, _added_keys(diff), batch_size=settings.reindex_batch_size
    )
    return diff, await _report(db, rtype, new_defs, settings, diff=diff, conflicts=conflicts)


def _refusal(rtype: RecordType, report: DryRunReport) -> str:
    return (
        f"{report.failing} of {report.checked} {rtype.key} record(s) would not satisfy the "
        "new schema; re-send with a default that makes them valid, or force=True to apply "
        "the change and mark them"
    )


async def _mark_pending(
    db: AsyncSession, rtype: RecordType, keys: list[str], *, whole_type: bool
) -> None:
    """Step 1 of §8.5, in the same transaction as the ``fields`` write.

    Every marked key is refused as a filter or a sort key — at the API, with a
    409 naming it — until the rebuild clears it. Partial results returned
    without comment are the failure mode the whole ceremony is for.
    """
    if not keys and not whole_type:
        return
    pending = pending_map(rtype)
    now = utcnow().isoformat()
    for key in keys:
        pending[key] = now
    if whole_type:
        pending[REINDEX_ALL] = now
    rtype.reindex_pending = pending
    db.add(rtype)
    await db.flush()


async def apply(
    db: AsyncSession,
    rtype: RecordType,
    *,
    fields_raw: list[dict[str, Any]] | None = None,
    expected_version: int,
    settings: RecordsSettings,
    actor: str | None = None,
    force: bool = False,
    orphaned: str | None = None,
    changes: dict[str, Any] | None = None,
) -> tuple[RecordType, SchemaDiff]:
    """Classify, refuse or write. Design §8.2, §8.5, §8.6, §8.8.

    ``fields_raw`` omitted keeps the current field list — that is the
    pointer-only edit (``display_field``/``slug_field``, passed in ``changes``
    with any other plain column), which still belongs here because a
    ``display_field`` change enqueues a whole-type rebuild.

    ``force=True`` applies a restrictive change **and leaves the failing rows
    untouched**. They are not mutated, not hidden and not migrated: they read
    back with an ``invalid`` list naming the fields (§8.2/§8.3), and the next
    ordinary write of each one is what brings it up to the new shape.

    ``orphaned`` is ``"restore"`` or ``"discard"``, and is required exactly
    when the report carries ``orphaned_conflicts`` (§8.8). ``"restore"`` writes
    nothing: the read path already falls back to ``_orphaned`` for a declared
    key, the rebuild below indexes it from there, and each record's next write
    moves it back out. ``"discard"`` is the one bulk payload write in §8.

    The version bump is deliberately *not* the first statement, though §8.6
    describes it that way: the row lock is taken first and the version is
    checked against it, so a stale caller still gets its 409 before the scan —
    but the guarded ``UPDATE`` itself happens after the dry run, so a refusal
    leaves the transaction with nothing in it at all. "Nothing is written" is a
    property this module should have on its own, not one that depends on every
    caller remembering to roll back.
    """
    changes = dict(changes or {})
    new_defs, new_fields = (
        normalise(fields_raw, settings) if fields_raw is not None else (field_defs(rtype), None)
    )

    await lock_type(db, rtype)
    current = await reload(db, RecordType, rtype.id)
    if current is None:  # pragma: no cover - the caller loaded it a moment ago
        raise NotFound(f"no record type with id {rtype.id!r}")
    if current.version != expected_version:
        raise Conflict(f"record type {rtype.key!r} has changed since it was read", current=current)

    if new_fields is not None:
        await check_targets(db, new_defs, rtype.key)
    check_pointers(
        new_defs,
        changes.get("display_field", rtype.display_field),
        changes.get("slug_field", rtype.slug_field),
    )

    diff = diff_fields(field_defs(rtype), new_defs)
    conflicts = await _orphaned.count_conflicts(
        db, rtype, _added_keys(diff), batch_size=settings.reindex_batch_size
    )
    if conflicts and orphaned not in _orphaned.CHOICES:
        raise OrphanedKeyConflict(conflicts)
    # Under ``discard`` the orphaned values are about to go, so the dry run
    # must judge each record without them — otherwise a change is refused for
    # values the operator has already said to throw away.
    drop = frozenset(conflicts) if orphaned == _orphaned.DISCARD else frozenset()
    report = await _report(
        db, rtype, new_defs, settings, diff=diff, conflicts=conflicts, drop_keys=drop
    )
    if report.failing and not force:
        raise SchemaChangeRefused(report, _refusal(rtype, report))

    pointer_moved = any(
        name in changes and changes[name] != getattr(rtype, name) for name in _POINTERS
    )
    display_moved = "display_field" in changes and changes["display_field"] != rtype.display_field

    if not await guarded_bump(db, RecordType, rtype.id, expected_version):  # pragma: no cover
        # Unreachable while the row lock holds; kept because on SQLite the lock
        # compiles to nothing, and a lost race must still be a 409.
        raise Conflict(
            f"record type {rtype.key!r} has changed since it was read",
            current=await reload(db, RecordType, rtype.id),
        )
    for name, value in changes.items():
        setattr(rtype, name, value)
    if new_fields is not None:
        rtype.fields = new_fields
        rtype.schema_version = rtype.schema_version + 1
    rtype.version = expected_version + 1
    rtype.updated_by = actor
    db.add(rtype)
    await db.flush()
    if new_fields is not None or pointer_moved:
        await snapshot(db, rtype, actor)

    if orphaned == _orphaned.DISCARD and conflicts:
        await _orphaned.discard(db, rtype, list(conflicts), batch_size=settings.reindex_batch_size)
    # ``display_field`` feeds every record's denormalised ``display_title``
    # (§18 Q2), so changing it is a whole-type rebuild. ``slug_field`` is not:
    # a slug is an address, and regenerating the ones already handed out would
    # break every link to them and can collide with a slug since taken. Only
    # records written after the change take the new pointer.
    await _mark_pending(
        db, rtype, list(diff.keys(ChangeClass.INDEX_AFFECTING)), whole_type=display_moved
    )
    return rtype, diff


async def rollback(
    db: AsyncSession,
    rtype: RecordType,
    *,
    to_version: int,
    expected_version: int,
    settings: RecordsSettings,
    actor: str | None = None,
    force: bool = False,
    orphaned: str | None = None,
) -> tuple[RecordType, SchemaDiff]:
    """Write an earlier schema revision back, as a new change (§8.6).

    Not a restore in the "put the row back" sense: the earlier ``fields`` go
    through :func:`apply` and are classified against what is stored *now*.
    Undoing a field deletion is therefore an addition — and one that will meet
    §8.8's orphaned-key refusal, which is the point: the values are still
    there, and whether they come back is the operator's call, not the undo's.
    """
    revision = (
        (
            await db.execute(
                select(RecordTypeRevision).where(
                    RecordTypeRevision.type_id == rtype.id,
                    RecordTypeRevision.version == to_version,
                )
            )
        )
        .scalars()
        .first()
    )
    if revision is None:
        raise NotFound(f"record type {rtype.key!r} has no revision at version {to_version}")
    return await apply(
        db,
        rtype,
        fields_raw=list(revision.fields or []),
        expected_version=expected_version,
        settings=settings,
        actor=actor,
        force=force,
        orphaned=orphaned,
        changes={
            "display_field": revision.display_field,
            "slug_field": revision.slug_field,
        },
    )
