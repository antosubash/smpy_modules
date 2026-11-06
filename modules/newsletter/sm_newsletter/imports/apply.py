"""One batch of staged rows, applied in the caller's transaction (R2, R3, R5, R15, D1, D8).

Lock order: records first (its contract takes the list's type lock, then row locks), then
newsletter's suppression rows. Nothing here commits; the runner commits only when its fenced
job ``UPDATE`` matched (D3).

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
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from simple_module_db import mark_written
from sm_records.contracts.newsletter_import import (
    MAX_IMPORT_BATCH,
    ImportResult,
    ImportRow,
    ImportTargets,
    import_subscribers,
    opted_out_anywhere,
)
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.constants import REASON_IMPORTED_CLEANED, REASON_UNSUBSCRIBED
from sm_newsletter.core.suppression import suppress_many, suppressed
from sm_newsletter.models import ImportEntry, ImportJob

__all__ = ["CLEANED", "SKIPPED_SUPPRESSED", "BatchResult", "apply_batch"]

SKIPPED_SUPPRESSED = "skipped_suppressed"
CLEANED = "cleaned"
SOURCE = "import"
_CREATED = frozenset({"created"})


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


def _chunks(items: Sequence[Any]) -> list[Sequence[Any]]:
    return [items[i : i + MAX_IMPORT_BATCH] for i in range(0, len(items), MAX_IMPORT_BATCH)]


async def _refused(session: AsyncSession, tenant_id: str, emails: list[str]) -> set[str]:
    """The subscribed addresses that may not be admitted: suppressed here, or opted out of
    any of the tenant's lists in records (D1). Reads only, before any records write."""
    if not emails:
        return set()
    refused = set(await suppressed(session, tenant_id=tenant_id, emails=emails))
    for chunk in _chunks(emails):
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
    records_settings: Any,
    now: datetime,
) -> list[ImportResult]:
    columns, tag_map = _columns(job, targets), _tag_map(job)
    results: list[ImportResult] = []
    for chunk in _chunks(rows):
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


def _error(row: ImportEntry, code: str, field_key: str | None) -> dict[str, Any]:
    return {"file": row.file_index, "line": row.line, "code": code, "field": field_key}


def _tally(result: BatchResult, row: ImportEntry, outcome: str) -> None:
    """R15: every row lands in exactly one count."""
    if row.kind == "subscribed":
        if outcome in _CREATED:
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
    subscribed = [r for r in rows if r.kind == "subscribed"]
    refused = await _refused(session, tenant_id, [r.email for r in subscribed])
    to_records: list[ImportEntry] = []
    for row in rows:
        if row.kind == "subscribed" and row.email in refused:
            outcome[row.id] = SKIPPED_SUPPRESSED
        elif row.kind in ("subscribed", "unsubscribed"):
            to_records.append(row)
        else:
            outcome[row.id] = CLEANED
    answers = await _to_records(
        session,
        tenant_id=tenant_id,
        job=job,
        rows=to_records,
        targets=targets,
        records_settings=records_settings,
        now=now,
    )
    for row, answer in zip(to_records, answers, strict=True):
        outcome[row.id] = answer.outcome
        result.errors.extend(_error(row, "invalid_value", key) for key in answer.dropped)
        if answer.outcome == "invalid":
            result.errors.append(_error(row, "record_refused", None))
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
    if left:
        await suppress_many(
            session,
            tenant_id=tenant_id,
            emails=left,
            reason=REASON_UNSUBSCRIBED,
            list_type_key=job.list_type_key,
            source=SOURCE,
            refresh=False,
            now=now,
        )
    if cleaned:
        await suppress_many(
            session,
            tenant_id=tenant_id,
            emails=cleaned,
            reason=REASON_IMPORTED_CLEANED,
            list_type_key="",
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
