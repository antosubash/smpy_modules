"""Changing a populated type's schema — the whole of design doc §8, applied.

Three entry points, one pipeline: :func:`preview` classifies a proposed
``fields`` list and reports what it would do to the records that exist,
writing nothing; :func:`apply` re-runs that classification and then writes —
re-run rather than trusting a report id, because a report taken minutes ago
is a report about a different database (§8.9), with the one narrow exception
``_preview.reused_report`` argues for; :func:`rollback`
writes an earlier :class:`RecordTypeRevision` back through :func:`apply`, so
an undo is classified, and refusable, like any other change (§8.6).

**The payload never migrates here.** A restrictive change applied with
``force`` leaves the failing rows exactly as they were: *marked*, not mutated
and not hidden (§8.3 — ``services.records.read_view`` reports them under
``invalid``). The only rows this module rewrites are the reserved
``_orphaned`` sub-key on an explicit ``discard``, and the index, which is
derived and rebuilt out of request (§8.5, :mod:`reindex_runner`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import REINDEX_ALL
from sm_records.index.reindex import pending_map
from sm_records.models import RecordType
from sm_records.schema.changes import DryRunReport, SchemaDiff
from sm_records.schema.diff import diff_fields
from sm_records.schema.types import ChangeClass
from sm_records.services import _orphaned
from sm_records.services._claims import lock_type
from sm_records.services._common import guarded_bump, reload, utcnow
from sm_records.services._dry_run import change_report, refusal
from sm_records.services._payload import field_defs
from sm_records.services._preview import MISSING, pointer_preview_changes, reused_report

# Re-exported: an undo is an ``apply`` of an earlier revision, so it belongs to
# this module's surface; it lives in ``_rollback`` for the 300-line cap.
from sm_records.services._rollback import rollback
from sm_records.services._schema import check_pointers, check_targets, normalise, snapshot
from sm_records.services.errors import (
    Conflict,
    NotFound,
    OrphanedKeyConflict,
    SchemaChangeRefused,
)
from sm_records.settings import RecordsSettings

__all__ = ["MISSING", "apply", "preview", "rollback"]

_POINTERS = ("display_field", "slug_field")


def _added_keys(diff: SchemaDiff) -> list[str]:
    return [c.field_key for c in diff.changes if c.what == "field_added"]


async def preview(
    db: AsyncSession,
    rtype: RecordType,
    fields_raw: list[dict[str, Any]],
    settings: RecordsSettings,
    *,
    display_field: Any = MISSING,
    slug_field: Any = MISSING,
    rescan: bool = False,
    on_progress: Callable[[int], None] | None = None,
) -> tuple[SchemaDiff, DryRunReport]:
    """Classify a proposed ``fields`` list and dry-run it. Writes nothing.

    ``display_field``/``slug_field`` default to :mod:`_preview`'s ``MISSING``
    (re-exported here), not ``None`` — a caller that left a pointer out must
    not be read as clearing it. A ``display_field`` change is folded into the
    diff as an index-affecting entry, so a pointer-only edit still previews.

    ``on_progress`` belongs to the deferred path (``services.preview_jobs``):
    the scan reports its ``checked`` count per batch for a polling client, and
    is ``None`` when the caller is waiting. ``rescan`` scans even when the
    diff says nothing could have broken (``_dry_run.change_report``): sent
    with the *stored* fields it answers "which records does the schema refuse
    now", the worklist a forced restrictive change leaves and that an empty
    diff otherwise reports as ``failing=0``. It is also the one preview that
    **writes**: what it finds is recorded on each record's ``invalid_since``,
    so the answer outlives the report the operator is reading.
    """
    new_defs, _ = normalise(fields_raw, settings)
    diff = diff_fields(field_defs(rtype), new_defs)
    pointer_changes = pointer_preview_changes(rtype, display_field, slug_field)
    if pointer_changes:
        diff = SchemaDiff(changes=(*diff.changes, *pointer_changes))
    conflicts = await _orphaned.count_conflicts(
        db, rtype, _added_keys(diff), batch_size=settings.reindex_batch_size
    )
    report = await change_report(
        db,
        rtype,
        new_defs,
        settings,
        diff=diff,
        conflicts=conflicts,
        rescan=rescan,
        # A rescan is a scan of the schema the records are *stored* against,
        # so what it finds is true of the install and is written down
        # (``services._invalid``). A draft preview scans a proposal that may
        # never be saved, and marking from one would flag records against a
        # schema nobody applied — which is also what keeps "Preview changes"
        # a button that writes nothing.
        mark=rescan,
        on_progress=on_progress,
    )
    return diff, report


async def _mark_pending(
    db: AsyncSession, rtype: RecordType, keys: list[str], *, whole_type: bool
) -> None:
    """Step 1 of §8.5, in the same transaction as the ``fields`` write. Every
    marked key is refused as a filter or a sort key — a 409 naming it — until
    the rebuild clears it; partial results without comment is the failure
    mode this ceremony is for."""
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
    ``fields_raw`` omitted keeps the current field list — the pointer-only edit
    (``display_field``/``slug_field``, in ``changes`` with any other plain
    column), which belongs here because ``display_field`` enqueues a rebuild.

    ``force=True`` applies a restrictive change **and leaves the failing rows
    untouched** — not mutated, not hidden, not migrated: they read back with an
    ``invalid`` list naming the fields (§8.2/§8.3), and each one's next
    ordinary write brings it up to the new shape.

    ``orphaned`` is ``"restore"`` or ``"discard"``, required exactly when the
    report carries ``orphaned_conflicts`` (§8.8). ``"restore"`` writes nothing
    — the read path already falls back to ``_orphaned`` for a declared key —
    but is still dry-run first and still refusable: §8.8 offers a restore where
    the values *validate*, and values written under a definition that has since
    changed need not. ``"discard"`` is the one bulk payload write.

    A ``fields_raw`` equal to what is stored is not a change: the schema bump,
    the revision snapshot and the rebuild are skipped, and only ``version``
    moves.

    The version bump is deliberately *not* the first statement, though §8.6
    describes it that way: the row lock and version check happen first, so a
    stale caller gets its 409 before the scan — but the guarded ``UPDATE``
    happens after the dry run, so a refusal leaves nothing written as a
    property of this module rather than of callers remembering to roll back.
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

    if new_fields is not None and new_fields == list(rtype.fields or []):
        # A resend of the list already stored is not a schema change, and
        # ``rollback`` sends one whenever an operator undoes something that
        # touched only a pointer or a label — or rolls back to where they are.
        # Treated as a change it would bump ``schema_version``, which restamps
        # nothing but marks every record ``schema_stale``, snapshot a revision
        # identical to the last, and rebuild the whole index for no difference.
        # ``version`` still moves below: the row was written (``updated_by``),
        # which is what ``update_type`` does for any other no-op edit.
        new_fields = None

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
    # The scan is the expensive half of a schema change on a large type, so
    # "Preview changes" then "Save" pays for one pass rather than two when the
    # two describe the same thing — ``_preview.reused_report`` says when.
    #
    # **A forced change never reuses one.** Its scan does not only decide the
    # refusal, it writes ``invalid_since`` on the records it leaves behind
    # (``services._invalid``), and a preview's report is a report: it recorded
    # nothing. So a force pays for its own pass, which is the pass that
    # produces the worklist. An unforced apply scans with ``mark=True`` too —
    # the change is about to be stored, so a record the new schema accepts is
    # one whose mark should go.
    report = (
        None
        if force
        else reused_report(
            rtype,
            current_version=current.version,
            fields_raw=new_fields if new_fields is not None else list(rtype.fields or []),
            display_field=changes.get("display_field", rtype.display_field),
            slug_field=changes.get("slug_field", rtype.slug_field),
            settings=settings,
            drop_keys=drop,
        )
    ) or await change_report(
        db, rtype, new_defs, settings, diff=diff, conflicts=conflicts, drop_keys=drop, mark=True
    )
    if report.failing and not force:
        raise SchemaChangeRefused(report, refusal(rtype, report))

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
    # (§18 Q2), so changing it is a whole-type rebuild; ``slug_field`` is not —
    # a slug is an address, and regenerating one handed out breaks every link.
    await _mark_pending(
        db, rtype, list(diff.keys(ChangeClass.INDEX_AFFECTING)), whole_type=display_moved
    )
    return rtype, diff
