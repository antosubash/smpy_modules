"""One batch of staged rows, applied in the caller's transaction (R2, R3, R5, R15, D1, D8).

Lock order: records' opt-out lock of every address of the batch (ascending key) and the
list's type lock (``lock_import_batch``, before the refusal read), then records' row locks,
then newsletter's suppression rows. Every unsubscribe takes the address lock first too, so
the refusal read holds until the batch commits (on SQLite the type lock's ``UPDATE`` is the
write lock). Nothing here commits; the runner commits only if its fenced ``UPDATE`` matched.

The HARD invariant, newsletter's half:

* a *subscribed* row whose address newsletter suppresses (any reason, any list) **or** records
  holds ``unsubscribed`` on any of the tenant's lists, trash included (D1), is never handed to
  records: it is ``skipped_suppressed`` and nothing else;
* suppressions are only ever inserted (``refresh=False``: insert-ignore), never cleared or
  freshened, so an existing ``hard_bounce`` / ``complaint`` / opt-out keeps its ``created_at``;
* records' import publishes nothing (R5), so no ``pending -> confirmed`` reaches the mirror.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from itertools import batched
from typing import Any

from simple_module_db import mark_written
from sm_records.contracts.newsletter_import import (
    MAX_IMPORT_BATCH,
    ImportResult,
    ImportRow,
    ImportTargets,
    import_subscribers,
    lock_import_batch,
    opted_out_anywhere,
)
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.constants import REASON_IMPORTED_CLEANED, REASON_UNSUBSCRIBED
from sm_newsletter.core.suppression import suppress_many, suppressed
from sm_newsletter.imports.constants import KINDS
from sm_newsletter.models import ImportEntry, ImportJob

__all__ = ["CLEANED", "SKIPPED_SUPPRESSED", "BatchResult", "apply_batch"]

SKIPPED_SUPPRESSED = "skipped_suppressed"
CLEANED = "cleaned"
SOURCE = "import"


@dataclass
class BatchResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    suppressed: int = 0
    failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    """``{file, line, code, field}``; ``field`` is a list field key, never a value (R16)."""

    @property
    def processed(self) -> int:
        return self.created + self.updated + self.skipped + self.suppressed + self.failed


async def _refused(
    session: AsyncSession, tenant_id: str, job: ImportJob, rows: list[ImportEntry]
) -> set[str]:
    """The batch's locks (every address, then the list), then the subscribed addresses that
    may not be admitted: suppressed here, or opted out of any of the tenant's lists (D1)."""
    emails = [r.email for r in rows]
    await lock_import_batch(session, tenant_id=tenant_id, type_key=job.list_type_key, emails=emails)
    emails = [r.email for r in rows if r.kind == "subscribed"]
    if not emails:
        return set()
    refused = set(await suppressed(session, tenant_id=tenant_id, emails=emails))
    for chunk in batched(emails, MAX_IMPORT_BATCH):
        refused |= await opted_out_anywhere(session, tenant_id=tenant_id, emails=list(chunk))
    return refused


def _record_row(row: ImportEntry, columns: dict[str, str], tag_map: dict[str, str]) -> ImportRow:
    if row.kind != "subscribed":  # R4: an unsubscribed record carries the address only
        return ImportRow(email=row.email, status="unsubscribed", unsubscribed_at=row.event_at)
    values = {key: str(row.fields[col]) for col, key in columns.items() if col in row.fields}
    tags: list[str] = []
    for label in row.tags or []:
        value = tag_map.get(label)
        if value is not None and value not in tags:
            tags.append(value)
    return ImportRow(
        email=row.email,
        status="confirmed",
        fields=values,
        tags=tags,
        confirmed_at=row.event_at,
        consent_at=row.consent_at,
    )


def _columns(job: ImportJob, targets: ImportTargets) -> dict[str, str]:
    """Column -> field key of the mapping, for the targets the list still has."""
    allowed = {f.key for f in targets.fields}
    chosen = (job.mapping or {}).get("fields") or {}
    return {str(col): key for col, key in chosen.items() if key in allowed}


def _tag_map(job: ImportJob) -> dict[str, str]:
    """Label -> the final choice value the tags step wrote into ``tags_found`` (D8)."""
    if not (job.mapping or {}).get("tags"):
        return {}
    return {t["label"]: t["value"] for t in job.tags_found or []}


async def _to_records(
    session: AsyncSession,
    *,
    tenant_id: str,
    job: ImportJob,
    rows: list[ImportEntry],
    targets: ImportTargets,
    tag_map: dict[str, str],
    records_settings: Any,
    now: datetime,
) -> list[ImportResult]:
    columns = _columns(job, targets)
    results: list[ImportResult] = []
    for chunk in batched(rows, MAX_IMPORT_BATCH):
        results.extend(
            await import_subscribers(
                session,
                tenant_id=tenant_id,
                type_key=job.list_type_key,
                rows=[_record_row(r, columns, tag_map) for r in chunk],
                settings=records_settings,
                now=now,
            )
        )
    return results


def _unmapped(row: ImportEntry, tag_map: dict[str, str]) -> bool:
    """A label with no value in ``tags_found``: staging refuses over ``MAX_NEW_TAGS`` distinct
    labels (T6a), so this cannot happen; if it ever does it is a row error, not a silent drop."""
    return any(label not in tag_map for label in row.tags or [])


def _error(row: ImportEntry, code: str, field_key: str | None) -> dict[str, Any]:
    return {"file": row.file_index, "line": row.line, "code": code, "field": field_key}


def _tally(result: BatchResult, row: ImportEntry, outcome: str) -> None:
    """R15: every row lands in exactly one count."""
    if row.kind == "subscribed":
        if outcome == "created":
            result.created += 1
        elif outcome == "updated":
            result.updated += 1
        elif outcome == "invalid":
            result.failed += 1
        else:
            result.skipped += 1
    elif outcome == "kept_confirmed":
        result.skipped += 1
    else:  # unsubscribed (an invalid one is still suppressed by hash) or cleaned
        result.suppressed += 1


async def apply_batch(
    session: AsyncSession,
    *,
    tenant_id: str,
    job: ImportJob,
    rows: list[ImportEntry],
    targets: ImportTargets,
    records_settings: Any,
    now: datetime,
) -> BatchResult:
    """Apply ``rows`` of ``job``: records, then suppressions, then each row's outcome."""
    result = BatchResult()
    outcome: dict[int | None, str] = {}
    tag_map = _tag_map(job)
    refused = await _refused(session, tenant_id, job, rows)
    to_records: list[ImportEntry] = []
    for row in rows:
        if row.kind not in KINDS:  # never a tenant-wide suppression for a kind not known here
            raise ValueError("unknown staged row kind")
        if row.kind == "subscribed" and row.email in refused:
            outcome[row.id] = SKIPPED_SUPPRESSED
        elif row.kind == "cleaned":
            outcome[row.id] = CLEANED
        else:
            to_records.append(row)
    answers = await _to_records(
        session,
        tenant_id=tenant_id,
        job=job,
        rows=to_records,
        targets=targets,
        tag_map=tag_map,
        records_settings=records_settings,
        now=now,
    )
    for row, answer in zip(to_records, answers, strict=True):
        outcome[row.id] = answer.outcome
        result.errors.extend(_error(row, "invalid_value", key) for key in answer.dropped)
        if answer.outcome == "invalid":
            result.errors.append(_error(row, "record_refused", None))
        if row.kind == "subscribed" and tag_map and _unmapped(row, tag_map):
            result.errors.append(_error(row, "tag_invalid", "tags"))
    await _suppress(session, tenant_id, job, rows, outcome, now)
    await _store(session, tenant_id, job, outcome)
    for row in rows:
        _tally(result, row, outcome[row.id])
    return result


async def _suppress(
    session: AsyncSession,
    tenant_id: str,
    job: ImportJob,
    rows: list[ImportEntry],
    outcome: dict[int | None, str],
    now: datetime,
) -> None:
    """Insert-ignore only: an existing row is never cleared, freshened or re-sourced."""
    left = [r.email for r in rows if r.kind == "unsubscribed" and outcome[r.id] != "kept_confirmed"]
    cleaned = [r.email for r in rows if r.kind == "cleaned"]
    for emails, reason, list_type_key in (
        (left, REASON_UNSUBSCRIBED, job.list_type_key),
        (cleaned, REASON_IMPORTED_CLEANED, ""),
    ):
        if emails:
            await suppress_many(
                session,
                tenant_id=tenant_id,
                emails=emails,
                reason=reason,
                list_type_key=list_type_key,
                source=SOURCE,
                refresh=False,
                now=now,
            )


async def _store(
    session: AsyncSession, tenant_id: str, job: ImportJob, outcome: dict[int | None, str]
) -> None:
    """One ``UPDATE`` per outcome, pinned to the tenant and the import."""
    grouped: dict[str, list[int | None]] = defaultdict(list)
    for row_id, value in outcome.items():
        grouped[value].append(row_id)
    for value, ids in sorted(grouped.items()):
        await session.execute(
            update(ImportEntry)
            .where(
                ImportEntry.tenant_id == tenant_id,
                ImportEntry.import_id == job.id,
                ImportEntry.id.in_(ids),  # ty: ignore[unresolved-attribute]
            )
            .values(outcome=value)
            .execution_options(synchronize_session=False)
        )
    if grouped:
        mark_written(session)
