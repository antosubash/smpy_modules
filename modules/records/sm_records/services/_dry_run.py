"""Would this schema change leave any record invalid? Design doc §8.2, §8.9.

A batched, read-only pass over every record of one type, validating each
against the *proposed* model. It writes nothing and it holds no lock: the
apply path re-runs it inline before writing, because a report taken minutes ago
against records that may have changed since is a report about a different
database (§8.9 says so explicitly, and that is why no report is ever
persisted).

The trash is included. A trashed record still holds content the schema
describes and a restore reads it back under the new shape, so a change that
would break it is a change the operator has to be told about — the same
reasoning ``record_count(include_deleted=True)`` follows everywhere else here.

:func:`needs_dry_run` and :func:`change_report` are the decision around the
scan — when it is worth a full pass, and what a report says when it is not.
They live here rather than in ``schema_change`` so the answer to "is a scan
needed" sits with the scan it guards.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import ORPHANED_KEY
from sm_records.models import Record, RecordType
from sm_records.schema.changes import DRY_RUN_SAMPLE, DryRunReport, FailingRecord, SchemaDiff
from sm_records.schema.compile import (
    PayloadValidationError,
    build_model,
    from_stored,
    validate_payload,
)
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import ChangeClass
from sm_records.services import _duplicates, _invalid
from sm_records.services._common import record_count, walk_type
from sm_records.services._payload import field_defs
from sm_records.settings import RecordsSettings


def _errors_for(model: type, view: dict[str, Any]) -> list[dict[str, str]]:
    try:
        validate_payload(model, view)  # ty: ignore[invalid-argument-type]
    except PayloadValidationError as exc:
        return exc.errors
    return []


def _payload_of(record: Record, drop_keys: frozenset[str]) -> dict[str, Any]:
    data = dict(record.data or {})
    if not drop_keys:
        return data
    orphaned = {k: v for k, v in (data.get(ORPHANED_KEY) or {}).items() if k not in drop_keys}
    data = {k: v for k, v in data.items() if k not in drop_keys}
    if orphaned:
        data[ORPHANED_KEY] = orphaned
    else:
        data.pop(ORPHANED_KEY, None)
    return data


async def dry_run(
    db: AsyncSession,
    rtype: RecordType,
    new_defs: list[FieldDefinition],
    *,
    batch_size: int,
    orphaned_conflicts: dict[str, int] | None = None,
    drop_keys: frozenset[str] = frozenset(),
    unique_pairs: Sequence[tuple[FieldDefinition, FieldDefinition]] = (),
    mark: bool = False,
    on_progress: Callable[[int], None] | None = None,
) -> DryRunReport:
    """Validate every record against ``new_defs`` without writing anything.

    The model is built with :func:`~sm_records.schema.compile.build_model`
    rather than ``get_model``: the proposed version does not exist yet, and
    caching a validator for a ``schema_version`` that may never be written
    would hand the next writer a shape nobody stored.

    Each record is read through :func:`~sm_records.schema.compile.from_stored`
    first — the same lenient read an API caller gets — so a row is judged on
    what it *reads as* under the new schema, defaults filled and values coerced
    (§8.4), not on the raw payload it happens to hold.

    ``on_progress`` is called with the running ``checked`` count once per
    batch — per batch and not per record, because it is what a polling client
    renders as "checked N of M" and a call per record would be a write to the
    job registry per record for a number nobody reads at that resolution. It
    is ``None`` on the synchronous path, where there is nobody to tell.

    ``drop_keys`` are removed from the payload before that read: they are the
    orphaned values an ``orphaned="discard"`` apply is about to throw away
    (§8.8), and judging a record on a value that will not survive the change
    would refuse the change for content nobody is keeping.

    ``mark`` writes what the pass found to ``Record.invalid_since`` — see
    :mod:`sm_records.services._invalid`, which says which callers may, and why
    a draft preview is not one of them.

    ``unique_pairs`` names the fields gaining ``unique``. They are the one
    restrictive class this per-record pass is structurally blind to —
    duplication is a property of a *pair* of records — so
    :mod:`sm_records.services._duplicates` answers for them: by a ``GROUP BY``
    against the index for a field that is already indexed, and by riding along
    on this walk for one that is not (a field gaining ``unique`` and
    ``indexed`` together has no rows to group yet).
    """
    model = build_model(rtype.key, rtype.schema_version + 1, new_defs)
    checked = failing = 0
    sample: list[FailingRecord] = []
    collector = _duplicates.Collector([old for old, _new in unique_pairs if not old.indexed])
    marker = _invalid.Marker(db, rtype, enabled=mark)
    async for batch in walk_type(db, rtype, batch_size):
        for record in batch:
            checked += 1
            view = from_stored(new_defs, _payload_of(record, drop_keys))
            if collector.active:
                collector.add(record, view, room=DRY_RUN_SAMPLE)
            errors = _errors_for(model, view)
            marker.judge(record, failed=bool(errors))
            if not errors:
                continue
            failing += 1
            if len(sample) < DRY_RUN_SAMPLE:
                sample.append(
                    FailingRecord(
                        uuid=record.uuid,
                        display_title=record.display_title or "",
                        errors=tuple(errors),
                    )
                )
        await marker.flush()
        if on_progress is not None:
            on_progress(checked)
    return _folded(
        checked,
        failing,
        sample,
        dict(orphaned_conflicts or {}),
        await _duplicates.scan(db, rtype, unique_pairs),
        collector.report(),
    )


def _folded(
    checked: int,
    failing: int,
    sample: list[FailingRecord],
    conflicts: dict[str, int],
    *reports: _duplicates.DuplicateReport,
) -> DryRunReport:
    """One report out of the payload pass and the duplicate scans.

    The duplicate counts go into ``failing`` — that is what makes the change
    refusable without ``force`` like every other restrictive failure — and are
    kept separately in ``duplicates`` as well, because the refusal has to be
    able to say that this is the one of them ``force`` does not leave
    recoverable. ``failing`` is capped at ``checked``: a record can fail a
    payload rule *and* hold a duplicate, and is counted by both.
    """
    extra = sum(report.failing for report in reports)
    per_key: dict[str, int] = {}
    for report in reports:
        per_key.update(report.per_key)
        sample = [*sample, *report.sample]
    return DryRunReport(
        checked=checked,
        failing=min(failing + extra, checked) if checked else failing + extra,
        sample=tuple(sample[:DRY_RUN_SAMPLE]),
        orphaned_conflicts=conflicts,
        duplicates=per_key,
    )


def needs_dry_run(diff: SchemaDiff, conflicts: dict[str, int]) -> bool:
    """Only a restrictive change can invalidate a record. An additive or
    index-affecting one cannot, by construction, and a destructive one takes
    the field away rather than the rows — so scanning the type for them would
    be a full pass that can only ever report zero (§8.2). A type change is
    already classified restrictive, so it is covered here.

    **Orphaned keys are the exception, and they are classified additive.**
    Re-adding a deleted key is ``field_added`` — nothing about the *diff* can
    invalidate a record — but the values that key still holds were written
    under the old definition and are read back under the new one
    (``schema.compile.from_stored`` falls back to ``_orphaned`` for a declared
    key), so ``price`` deleted as ``text`` and re-added as ``number`` can
    perfectly well come back as ``"oops"``. §8.8 only offers ``restore`` where
    the values validate, which is a claim nothing but the scan can make — so
    any orphaned conflict forces it, on ``preview`` and on ``apply`` alike.
    """
    if conflicts:
        return True
    return any(c.kind is ChangeClass.RESTRICTIVE for c in diff.changes)


async def change_report(
    db: AsyncSession,
    rtype: RecordType,
    new_defs: list[FieldDefinition],
    settings: RecordsSettings,
    *,
    diff: SchemaDiff,
    conflicts: dict[str, int],
    drop_keys: frozenset[str] = frozenset(),
    rescan: bool = False,
    mark: bool = False,
    on_progress: Callable[[int], None] | None = None,
) -> DryRunReport:
    """The report for one proposed change — scanned, or honestly skipped.

    ``rescan`` forces the scan whatever the diff says. The caller is the
    preview endpoint's "Check records", whose question is not "what would this
    change do" but "what does not fit the schema *as it is*" — and for that
    the diff is empty, ``needs_dry_run`` is ``False``, and the short circuit
    below would answer ``failing=0`` about records nothing looked at. It is
    the only way to re-derive the worklist a forced restrictive change leaves
    behind, since the stored fields are their own diff.

    ``mark`` is passed straight through; a skipped scan writes nothing.
    """
    if not rescan and not needs_dry_run(diff, conflicts):
        # Skipped, but ``checked`` still has to be an honest count of what
        # was skipped (incl. trash — §8.9's own reasoning for the delete
        # confirmation), or "N records checked, 0 would fail" lies about N.
        checked = await record_count(db, rtype, include_deleted=True)
        return DryRunReport(checked=checked, failing=0, orphaned_conflicts=conflicts)
    return await dry_run(
        db,
        rtype,
        new_defs,
        batch_size=settings.reindex_batch_size,
        orphaned_conflicts=conflicts,
        drop_keys=drop_keys,
        unique_pairs=_duplicates.newly_unique(diff, field_defs(rtype), new_defs),
        mark=mark,
        on_progress=on_progress,
    )


def refusal(rtype: RecordType, report: DryRunReport) -> str:
    """Why the change was refused, and what the operator can do instead.

    ``duplicates`` gets its own sentence because ``force`` means something
    different for it. Every other restrictive failure leaves a record
    *marked*: it reads back with an ``invalid`` list and its next ordinary
    write brings it up to the new shape. A record sharing a newly-unique value
    is marked too, but its next write cannot fix it — the value has to change
    on one side or the other first, or the field has to stop being unique.
    """
    text = (
        f"{report.failing} of {report.checked} {rtype.key} record(s) would not satisfy the new "
        "schema; re-send with a default that makes them valid, or force=True to apply the "
        "change and mark them"
    )
    if not report.duplicates:
        return text
    keys = ", ".join(f"{key!r} ({count})" for key, count in sorted(report.duplicates.items()))
    return (
        f"{text}. Some of them are duplicates of a value being made unique — {keys}. "
        "force=True marks these too, but unlike every other refusal here they cannot be "
        "fixed by editing the record: until one side's value changes, or the field stops "
        "being unique, only writes that leave that value alone are accepted"
    )
