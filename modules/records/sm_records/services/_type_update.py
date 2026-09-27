"""``update_type`` — one edit to a Record Type row, and where it is decided.

Split from :mod:`sm_records.services.types` for the 300-line cap. The seam is
the interesting rule rather than an arbitrary cut: a type with no records takes
the fast path here (validate, guard the version, write, snapshot), and a type
that holds any — the trash included — is handed to
:mod:`sm_records.services.schema_change`, which owns the whole of design §8.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import locales
from sm_records.models import RecordType, tables_for
from sm_records.services._common import bump_or_conflict, record_count
from sm_records.services._payload import field_defs
from sm_records.services._schema import (
    check_pointers,
    check_targets,
    check_type_text,
    normalise,
    pointers_moved,
    write_type_row,
)
from sm_records.services.errors import Conflict, ValidationFailed
from sm_records.services.schema_change import apply as apply_schema_change
from sm_records.settings import RecordsSettings

__all__ = ["update_type"]

#: Everything ``update_type`` accepts. ``key`` is absent on purpose — it is in
#: URLs, in the public API and in every relation target, so a rename would
#: strand all three (design §5).
_EDITABLE = frozenset(
    {
        "label",
        "label_plural",
        "description",
        "icon",
        "fields_raw",
        "display_field",
        "slug_field",
        "is_public",
        # A navigation flag, not a schema field: no classification, no dry
        # run, no revision and no ``schema_version`` bump — exactly the class
        # of change ``is_public`` is. What it *does* change is the admin
        # sidebar, which the endpoint layer notices (``sm_records.menu``);
        # this layer stays free of app and registry knowledge.
        "show_in_menu",
        "translatable",
        "allowed_roles",
    }
)

#: A change to any of these is snapshotted in ``records_type_revision``. The
#: rest are labels: they cannot damage a record, and a revision per typo would
#: bury the schema edits the table exists to make reversible.
_SNAPSHOT_TRIGGERS = ("fields_raw", "display_field", "slug_field")

_UNSET = object()
"""Distinguishes "the caller did not send ``collection``" from "the caller sent
``null``", which is a legal value meaning the global tables."""


def _check_collection_unchanged(rtype: RecordType, changes: dict[str, Any]) -> None:
    """``collection`` is set at creation and never after — Phase 5 §6.2.

    A 409 and not the 422 ``_EDITABLE`` would otherwise give, because this is
    not a malformed request: the caller asked for something coherent that this
    module will not do. Moving a populated type between collections means
    copying its records, revisions and index rows into other tables and
    re-pointing every reference at them, with no rollback story — so the
    refusal is the honest answer and the message says exactly that.

    An echo of the current value is dropped rather than refused: clients send
    back the whole type they just read, and a 409 for changing nothing would
    make every save of an unmodified form fail.
    """
    sent = changes.pop("collection", _UNSET)
    if sent is not _UNSET and sent != rtype.collection:
        raise Conflict("moving a populated type between collections is not supported")


async def _check_translatable(
    db: AsyncSession,
    rtype: RecordType,
    settings: RecordsSettings,
    translatable: bool | None,
) -> None:
    """Turning ``translatable`` **off** is refused while foreign-locale records
    exist (Phase 5 §4.1).

    Turning it on is additive — every existing record already carries the
    default locale, and nothing about them changes. Turning it off is not: the
    type's screens stop offering any language but the default, so a German
    record would stay in the database, keep its slug claim in German, keep
    answering ``?locale=de`` on the public API, and be unreachable from the
    admin UI. Refusing names the count, so the operator knows what has to be
    translated away or deleted first.

    The count includes the trash: a trashed record still owns its language in
    its group, and restoring it after the flag went off would recreate exactly
    the unreachable row this refuses.
    """
    if translatable is not False or not rtype.translatable:
        return
    cls = tables_for(rtype).record
    stmt = (
        select(func.count(cls.id))
        .where(cls.type_id == rtype.id, cls.locale != locales.default(settings))
        .execution_options(include_deleted=True)
    )
    held = int((await db.execute(stmt)).scalar_one())
    if held:
        raise Conflict(
            f"type {rtype.key!r} holds {held} record(s) in a locale other than "
            f"{locales.default(settings)!r}; translating them away or deleting them "
            "is what makes 'translatable' safe to turn off"
        )


async def update_type(
    db: AsyncSession,
    rtype: RecordType,
    *,
    expected_version: int,
    settings: RecordsSettings,
    actor: str | None = None,
    force: bool = False,
    orphaned: str | None = None,
    **changes: Any,
) -> RecordType:
    """Edit a type under optimistic concurrency (design §8.6).

    ``version`` is bumped by every accepted edit; ``schema_version`` only by a
    change to ``fields``, because it is what record rows stamp themselves with
    and what the compiled-model cache is keyed on. Bumping it for a label edit
    would invalidate every cached validator and mark every record stale for
    nothing.

    A ``fields_raw`` (or ``display_field``/``slug_field``) change on a type
    that holds records — the trash included — is handed to
    :func:`sm_records.services.schema_change.apply`, which classifies it,
    dry-runs it over those records and refuses what would invalidate them.
    ``force`` and ``orphaned`` are that path's two answers to a refusal (§8.2
    and §8.8) and are ignored on every other edit; they are named here rather
    than folded into ``**changes`` because they are not columns.
    """
    await _check_translatable(db, rtype, settings, changes.get("translatable"))
    _check_collection_unchanged(rtype, changes)
    unknown = sorted(set(changes) - _EDITABLE)
    if unknown:
        problem = (
            "key is immutable — it is in URLs, the API and every relation target"
            if "key" in unknown
            else f"cannot change {unknown}"
        )
        raise ValidationFailed(problem, [{"field": unknown[0], "message": problem}])
    check_type_text(changes)

    fields_raw = changes.pop("fields_raw", None)
    fields: list[dict[str, Any]] | None = None
    if fields_raw is not None:
        defs, fields = normalise(fields_raw, settings)
        if fields == list(rtype.fields or []):
            # A normalised resend of the same list is not a change: the stored
            # form is the validator's dump, so comparing raw input would make a
            # no-op save bump ``schema_version`` and enqueue a rebuild.
            fields, fields_raw = None, None
    else:
        defs = field_defs(rtype)

    if fields is not None or pointers_moved(rtype, changes):
        # Including the trash: a trashed record still holds content these
        # fields describe, and a restore reads it back under them.
        held = await record_count(db, rtype, include_deleted=True)
        if held:
            # Design §8 in full — classification, dry run, ``_orphaned``
            # decision, index migration. Only a populated type needs it: with
            # no records there is nothing to invalidate and nothing to
            # reindex, and routing an empty type through it would mark
            # ``reindex_pending`` that only the out-of-request runner clears.
            updated, _ = await apply_schema_change(
                db,
                rtype,
                fields_raw=fields_raw,
                expected_version=expected_version,
                settings=settings,
                actor=actor,
                force=force,
                orphaned=orphaned,
                changes=changes,
            )
            return updated
    if fields is not None:
        await check_targets(db, defs, rtype.key)

    check_pointers(
        defs,
        changes.get("display_field", rtype.display_field),
        changes.get("slug_field", rtype.slug_field),
    )

    await bump_or_conflict(db, RecordType, rtype.id, expected_version, f"record type {rtype.key!r}")
    await write_type_row(
        db,
        rtype,
        changes=changes,
        fields=fields,
        expected_version=expected_version,
        actor=actor,
        take_snapshot=fields is not None or any(n in changes for n in _SNAPSHOT_TRIGGERS),
    )
    return rtype
