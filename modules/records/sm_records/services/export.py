"""Streaming export of one type's records, as JSON or as CSV.

Three properties this module exists to hold, none of which survives a naive
``[record_row(r) for r in await db.execute(...)]``:

* **It never holds the type in memory.** The walk is keyset-paged by
  ``Record.id`` in batches of ``reindex_batch_size``, and each batch is
  expunged from the session's identity map before the next one is read. A
  100k-record type streams in constant memory; the same export built as a
  list is a list of 100k JSON payloads.
* **It is written as a JSON *stream*.** The array is opened, the rows are
  comma-separated as they are produced, and the array is closed — nobody
  calls ``json.dumps`` on the whole document, which would reintroduce exactly
  the buffer the paging removed.
* **What it exports is what a reader sees.** ``data`` comes from
  ``read_view`` (design §8.3's lenient read), so a record stamped at an older
  schema version exports with the current schema's defaults filled in rather
  than with holes. ``_orphaned`` is stripped: it is the undo buffer for
  deleted fields (§8.2), not content, and an import refuses it anyway.

The session is **not** the request's. The body of a ``StreamingResponse`` is
produced after the handler has returned, and FastAPI's ``yield`` dependencies
are unwound at a point that is a version detail rather than a guarantee — so
the generator opens its own read-only session from the app's session factory,
the same escape hatch ``endpoints/api/_errors.py`` uses. It also means a
20-minute export is not a 20-minute-old transaction on the request's session.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import ORPHANED_KEY
from sm_records.index.query import Filter, Sort, build_query, only_trashed
from sm_records.models import Record, RecordType, tables_for
from sm_records.schema.compile import to_jsonable
from sm_records.schema.fields import FieldDefinition

# Re-exported: how one *cell* is spelled — and escaped — lives in
# ``_export_cells`` for the file cap. See its docstring for the seam.
from sm_records.services._export_cells import (
    ENVELOPE_COLUMNS,
    csv_cell,
    csv_header,
    escape_formula,
)
from sm_records.services._payload import field_defs, read_view
from sm_records.services.types import get_type_by_id
from sm_records.settings import RecordsSettings

__all__ = [
    "ENVELOPE_COLUMNS",
    "csv_cell",
    "csv_header",
    "escape_formula",
    "export_filename",
    "iter_csv",
    "iter_json",
    "record_row",
    "walk_records",
]


def export_filename(type_key: str, suffix: str, *, today: date | None = None) -> str:
    """``<key>-<date>.<suffix>`` — dated, because the second thing anybody does
    with an export is find the one from last Tuesday."""
    stamp = (today or datetime.now().date()).isoformat()
    return f"{type_key}-{stamp}.{suffix}"


async def walk_records(
    db: AsyncSession,
    rtype: RecordType,
    *,
    settings: RecordsSettings,
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
    trashed: bool = False,
) -> AsyncIterator[list[Record]]:
    """The whole type, one batch at a time, in ``Record.id`` order.

    **Keyset, not ``OFFSET``**: ``WHERE id > :last LIMIT :batch`` costs the
    same on the last batch as on the first, while ``OFFSET n`` makes the
    database walk and discard ``n`` rows per batch — quadratic over the
    export, and the reason a 100k-row export used to take longer than the
    import that produced it.

    ``expunge_all`` between batches is the other half of the memory promise:
    without it every record stays in the session's identity map and the walk
    accumulates the whole type anyway, one batch at a time.

    An explicit ``sorts`` is the one case that cannot be keyset-paged here —
    the sort key lives in an index table reached through a semi-join, so
    "everything after the last row" is not a predicate over one column. That
    path pages by ``OFFSET`` and is meant for an export of a *selection* (the
    list screen's current filter and order); the default, unsorted export —
    what a round trip uses and what the UI's Export menu links to — is keyset.
    """
    batch = max(settings.reindex_batch_size, 1)
    fields = list(rtype.fields or [])
    record = tables_for(rtype).record
    last_id = 0
    offset = 0
    while True:
        stmt = build_query(rtype, fields, filters, sorts).limit(batch)
        stmt = stmt.offset(offset) if sorts else stmt.where(record.id > last_id)
        if trashed:
            stmt = only_trashed(record, stmt)
        rows = list((await db.execute(stmt)).scalars().all())
        if not rows:
            return
        yield rows
        if len(rows) < batch:
            return
        offset += batch
        last_id = int(rows[-1].id or 0)
        db.expunge_all()


def record_row(rtype: RecordType, record: Record, defs: list[FieldDefinition]) -> dict[str, Any]:
    """One record as the export file spells it.

    No audit columns, no ``version``, no ``is_deleted``, no ``schema_version``
    per row: those describe this install's copy of the row, and a file that
    carried them would invite an importer elsewhere to honour them. ``uuid``
    is the identity that *does* travel (§5), which is why the round trip does
    not depend on autoincrement.
    """
    view = read_view(rtype, record, with_invalid=False, defs=defs)["data"]
    view.pop(ORPHANED_KEY, None)
    return {
        "uuid": record.uuid,
        "slug": record.slug,
        "locale": record.locale,
        "translation_group": record.translation_group,
        "status": record.status.value,
        "position": record.position,
        "published_at": record.published_at.isoformat() if record.published_at else None,
        "data": to_jsonable(view),
    }


async def iter_json(
    session_factory: Callable[[], Any],
    type_id: int,
    *,
    settings: RecordsSettings,
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
    trashed: bool = False,
) -> AsyncIterator[str]:
    """``{"type": {...}, "records": [ ... ]}``, written as a stream."""
    async with session_factory() as db:
        rtype = await get_type_by_id(db, type_id)
        defs = field_defs(rtype)
        header = {
            "key": rtype.key,
            "schema_version": rtype.schema_version,
            "fields": list(rtype.fields or []),
        }
        yield '{"type": ' + json.dumps(header) + ', "records": ['
        first = True
        async for batch in walk_records(
            db, rtype, settings=settings, filters=filters, sorts=sorts, trashed=trashed
        ):
            chunk = []
            for record in batch:
                chunk.append(("" if first else ",") + json.dumps(record_row(rtype, record, defs)))
                first = False
            yield "".join(chunk)
        yield "]}"


async def iter_csv(
    session_factory: Callable[[], Any],
    type_id: int,
    *,
    settings: RecordsSettings,
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
    trashed: bool = False,
) -> AsyncIterator[str]:
    """RFC 4180: ``\\r\\n`` line endings, quoting only where it is needed,
    UTF-8 with **no** byte-order mark — a BOM is what makes the first column
    header read as ``\\ufeffuuid`` in every non-Excel reader, including this
    module's own importer."""
    async with session_factory() as db:
        rtype = await get_type_by_id(db, type_id)
        defs = field_defs(rtype)
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(csv_header(defs))
        yield _drain(buffer)
        async for batch in walk_records(
            db, rtype, settings=settings, filters=filters, sorts=sorts, trashed=trashed
        ):
            for record in batch:
                row = record_row(rtype, record, defs)
                data = row["data"]
                writer.writerow(
                    [
                        *(csv_cell(None, row[name]) for name in ENVELOPE_COLUMNS),
                        *(csv_cell(field, data.get(field.key)) for field in defs),
                    ]
                )
            yield _drain(buffer)


def _drain(buffer: Any) -> str:
    text = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return text
