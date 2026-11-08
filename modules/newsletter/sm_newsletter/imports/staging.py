"""Staging an upload into ``newsletter_import_row`` (R3 precedence, R6, R15).

Files are staged cleaned first, then unsubscribed, then subscribed, each row through
``insert_ignore`` on ``(tenant_id, import_id, email_hash)``: an insert that is skipped is a
duplicate, so an address in several files, or spelled two ways, is one row of the strongest
kind and is never created. Rows stream in ``STAGE_CHUNK`` batches; none is held. Nothing
commits: a refusal raised here is followed by the caller's rollback, which removes the job.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TextIO

from simple_module_db import mark_written
from sm_records.contracts.newsletter_admin import FieldChoice, SubscriberFilterError
from sm_records.contracts.newsletter_import import ImportTargets, importable_fields
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_import import ImportTooManyRows, ImportTooManyTags
from sm_newsletter.core.suppression import email_hash
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.core.upsert import insert_ignore
from sm_newsletter.imports import mapping
from sm_newsletter.imports.archive import Source
from sm_newsletter.imports.constants import (
    IGNORED,
    KEEP_ERRORS,
    KIND_ORDER,
    MAX_NEW_TAGS,
    MAX_ROWS,
    STAGE_CHUNK,
    STAGED,
)
from sm_newsletter.imports.mailchimp import (
    Header,
    Parsed,
    detect_kind,
    header_key,
    read_header,
    read_rows,
    text_stream,
)
from sm_newsletter.imports.tags import tag_values
from sm_newsletter.models import ImportEntry, ImportJob

__all__ = ["stage", "targets_for"]

_CONFLICT = ("tenant_id", "import_id", "email_hash")


@dataclass
class _Tally:
    seq: int = 0
    total: int = 0
    duplicates: int = 0
    invalid: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    errors_total: int = 0

    def error(self, file: int, line: int, code: str, field_key: str | None) -> None:
        self.errors_total += 1
        if len(self.errors) < KEEP_ERRORS:
            self.errors.append({"file": file, "line": line, "code": code, "field": field_key})


@dataclass(frozen=True)
class _Peek:
    source: Source
    kind: str
    header: Header | None


async def stage(
    session: AsyncSession,
    *,
    tenant_id: str,
    list_type_key: str,
    sources: Sequence[Source],
    created_by: str | None,
    now: datetime,
) -> ImportJob:
    """The ``staged`` import of ``sources`` into the list ``list_type_key``, flushed, not
    committed. :class:`NotFound` for no such list, ``ImportTooManyRows`` /
    ``ImportTooManyTags`` over the limits."""
    targets = await targets_for(session, tenant_id, list_type_key)
    existing = targets.tag_choices  # indexed or not (T6b): list_fields sees indexed only
    peeks = [_peek(s) for s in sources]
    columns, remaps = _columns(peeks)
    with tenant_scope(tenant_id):
        job = ImportJob(
            tenant_id=tenant_id,
            list_type_key=list_type_key,
            status=STAGED,
            created_by=created_by,
            created_at=now,
        )
        session.add(job)
        await session.flush()
    tally, rows_per_file = _Tally(), {}
    for position in sorted(
        (i for i, p in enumerate(peeks) if p.kind != IGNORED),
        key=lambda i: KIND_ORDER[peeks[i].kind],
    ):
        rows_per_file[position] = await _stage_file(
            session, tenant_id, job.id, peeks[position], remaps[position], tally
        )
    tags_found = await _tags_found(session, tenant_id, job.id, existing)
    job.files = [
        {"name": p.source.name, "kind": p.kind, "rows": rows_per_file.get(i, 0)}
        for i, p in enumerate(peeks)
    ]
    job.columns = columns
    job.tags_found = tags_found
    job.total, job.duplicates, job.invalid = tally.total, tally.duplicates, tally.invalid
    job.errors, job.errors_total = tally.errors, tally.errors_total
    job.mapping = mapping.suggest(columns, targets, tags_found)
    await session.flush()
    mark_written(session)
    return job


async def targets_for(session: AsyncSession, tenant_id: str, key: str) -> ImportTargets:
    """What the list ``key`` can import into; :class:`NotFound` when it is gone or no longer a
    list (the one place both the upload and the mapping routes read it)."""
    try:
        targets = await importable_fields(session, tenant_id=tenant_id, type_key=key)
    except SubscriberFilterError:
        raise NotFound() from None
    if targets is None:
        raise NotFound()
    return targets


@contextmanager
def _text(source: Source) -> Iterator[TextIO]:
    """The file as text; a stream the source owns (a ZIP entry) is closed after, a CSV upload's
    is left to its caller."""
    binary = source.open()
    try:
        yield text_stream(binary)
    finally:
        if source.owned:
            binary.close()


def _peek(source: Source) -> _Peek:
    """Header and kind of one file."""
    with _text(source) as stream:
        header = read_header(stream)
    return _Peek(source, detect_kind(source.name, header), header)


def _columns(peeks: Sequence[_Peek]) -> tuple[list[dict[str, str]], list[dict[int, int]]]:
    """The union of the staged files' mappable headers (by header key, first seen first), and
    per file the map from its column positions to the union's."""
    columns: list[dict[str, str]] = []
    index: dict[str, int] = {}
    remaps: list[dict[int, int]] = []
    for peek in peeks:
        remap: dict[int, int] = {}
        if peek.kind != IGNORED and peek.header is not None:
            for position in peek.header.mappable:
                name = peek.header.names[position]
                key = header_key(name)
                if key not in index:
                    index[key] = len(columns)
                    columns.append({"key": key, "header": name})
                remap[position] = index[key]
        remaps.append(remap)
    return columns, remaps


async def _stage_file(
    session: AsyncSession,
    tenant_id: str,
    job_id: int | None,
    peek: _Peek,
    remap: dict[int, int],
    tally: _Tally,
) -> int:
    """Stream one file into chunks; the rows of it that were staged."""
    buffer: list[dict[str, Any]] = []
    staged = 0
    seen = 0

    async def flush() -> None:
        nonlocal staged
        if not buffer:
            return
        inserted = await insert_ignore(session, ImportEntry.__table__, buffer, conflict=_CONFLICT)  # type: ignore[arg-type]
        tally.duplicates += len(buffer) - inserted
        tally.total += inserted
        staged += inserted
        buffer.clear()
        if tally.total > MAX_ROWS:
            raise ImportTooManyRows

    with _text(peek.source) as stream:
        header = read_header(stream)
        for item in read_rows(stream, header, peek.kind):
            seen += 1
            if seen % STAGE_CHUNK == 0:
                await asyncio.sleep(0)  # rows that never reach a flush must not starve the loop
            if not isinstance(item, Parsed):
                tally.error(peek.source.index, item.line, item.code, item.field)
                if item.code == "invalid_email":
                    tally.invalid += 1
                continue
            tally.seq += 1
            buffer.append(
                {
                    "tenant_id": tenant_id,
                    "import_id": job_id,
                    "seq": tally.seq,
                    "file_index": peek.source.index,
                    "line": item.line,
                    "kind": peek.kind,
                    "email": item.email,
                    "email_hash": email_hash(item.email),
                    "fields": {str(remap[i]): v for i, v in item.fields.items()},
                    "tags": item.tags,
                    "event_at": item.event_at,
                    "consent_at": item.consent_at,
                    "outcome": None,
                }
            )
            if len(buffer) >= STAGE_CHUNK:
                await flush()
        await flush()
    return staged


async def _tags_found(
    session: AsyncSession, tenant_id: str, job_id: int | None, existing: Sequence[FieldChoice]
) -> list[dict[str, Any]]:
    """``[{label, value, count}]`` over the subscribed rows that were staged, most frequent
    first; ``ImportTooManyTags`` when there are more than ``MAX_NEW_TAGS`` distinct labels
    (T6a), so every label of every row is here and none is dropped at apply. ``value`` is a
    preview: the tags step decides the final one (D8)."""
    stmt = select(ImportEntry.tags).where(
        ImportEntry.tenant_id == tenant_id,
        ImportEntry.import_id == job_id,
        ImportEntry.kind == "subscribed",
    )
    counts: Counter[str] = Counter()
    async for batch in (
        await session.stream_scalars(stmt.execution_options(yield_per=STAGE_CHUNK))
    ).partitions():
        for labels in batch:
            counts.update(labels or [])
    if len(counts) > MAX_NEW_TAGS:
        raise ImportTooManyTags
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    values = tag_values([label for label, _ in top], existing)
    return [{"label": label, "value": values[label], "count": n} for label, n in top]
