"""Upload and the parse step: an ``.ics`` becomes staged items a person can preview (Ruling 21).

**Upload.** :func:`read_upload` reads the part in chunks and stops at the cap (a declared size over
it is refused unread), sniffing that it begins like a calendar. :func:`create_import` needs
``events.manage`` and the right to write events in the calendar, refuses past
``IMPORT_ACTIVE_MAX`` unfinished imports and stores the raw bytes on the row (``source``), with
the importer's ``events.*`` permissions (``grants``) for the worker to re-check the calendar's
policy with: it has no session to ask.

**Parse.** :func:`parse_step` runs under a lease (:mod:`~sm_events.feeds.importing.fence`):
scan and map in a thread (pure, bounded), one query for the calendar's UIDs (the trash included,
because the unique key spans it), the items in chunks, the counts, and ``source = NULL``, all in
the caller's one transaction, so a crash leaves the import ``uploaded``/``parsing`` with no
items and the janitor relaunches it. A file that breaks a bound, or a failure in mapping, fails
the import with a **code** (the exception's message can echo the file and is never stored).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Literal

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import func, select

from sm_events.core import constants, timezones
from sm_events.core.access.rights import writable_calendar
from sm_events.core.errors import (
    Forbidden,
    IcsInvalid,
    ImportBusy,
    ImportFailure,
    ImportTenantBusy,
    ImportTooLarge,
)
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.core.text_safety import strip_unsafe
from sm_events.feeds.importing.fence import fenced
from sm_events.feeds.importing.mapper import Mapped, map_calendar
from sm_events.feeds.importing.preview_diff import is_unchanged
from sm_events.feeds.importing.scan import scan, sniff
from sm_events.feeds.importing.verdicts import existing_uids, item_row
from sm_events.models import Calendar, Category, EventImport

__all__ = [
    "create_import",
    "effective_max_bytes",
    "grants_of",
    "parse_step",
    "read_upload",
    "safe_filename",
]

logger = logging.getLogger(__name__)
_UNFINISHED = ("uploaded", "parsing", "staged", "queued", "running")
_SEPARATORS = re.compile(r"[\\/]+")


def effective_max_bytes(settings: EventsSettings) -> int:
    """The stored ``import_max_bytes``, kept between the floor and the ceiling."""
    return max(
        constants.IMPORT_MIN_BYTES, min(constants.IMPORT_BODY_CEILING, settings.import_max_bytes)
    )


async def read_upload(file: Any, *, limit: int) -> bytes:
    """``file`` (an ``UploadFile``) read in chunks, never past ``limit``: ``ImportTooLarge`` as
    soon as it would, before the rest is read; ``IcsInvalid`` when it does not begin like one."""
    if file.size is not None and file.size > limit:
        raise ImportTooLarge
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(constants.IMPORT_READ_CHUNK):
        if not chunks and not sniff(chunk):
            raise IcsInvalid
        total += len(chunk)
        if total > limit:
            raise ImportTooLarge
        chunks.append(chunk)
    if not chunks:
        raise IcsInvalid
    return b"".join(chunks)


def safe_filename(raw: str) -> str:
    """The file's base name for the screen: no path, no control or direction characters."""
    name = strip_unsafe(_SEPARATORS.split(raw or "")[-1]).strip()[: constants.IMPORT_FILENAME_MAX]
    return name or constants.IMPORT_FILENAME_FALLBACK


def grants_of(who: ResourcePrincipal) -> list[str]:
    """The importer's ``events.*`` permissions (and a wildcard), as stored on the import."""
    return sorted(p for p in who.permissions if p == "*" or p.startswith("events."))


async def create_import(
    db: Any,
    who: ResourcePrincipal,
    *,
    calendar_id: uuid.UUID,
    filename: str,
    data: bytes,
    now: datetime,
) -> EventImport:
    """A new ``uploaded`` import. ``Forbidden`` without ``events.manage``, ``NotFound`` /
    ``Forbidden`` for the calendar (the policy's own), ``ImportBusy`` past the active cap."""
    if not who.has(constants.PERM_MANAGE):
        raise Forbidden
    await writable_calendar(db, who, calendar_id)
    where = (
        EventImport.tenant_id == bound_tenant(),  # type: ignore[arg-type]
        EventImport.status.in_(_UNFINISHED),  # type: ignore[attr-defined]
    )

    async def count(*extra: Any) -> int:
        stmt = select(func.count()).select_from(EventImport).where(*where, *extra)
        return (await db.execute(stmt)).scalar_one()

    # One user cannot fill the tenant's slots; the tenant has a larger ceiling of its own.
    if await count(EventImport.created_by == who.user_id) >= constants.IMPORT_ACTIVE_MAX:  # type: ignore[arg-type]
        raise ImportBusy
    if await count() >= constants.IMPORT_ACTIVE_TENANT_MAX:
        raise ImportTenantBusy
    row = EventImport(
        calendar_id=calendar_id,
        created_by=who.user_id or "",
        status="uploaded",
        filename=safe_filename(filename),
        size_bytes=len(data),
        source=data,
        grants=grants_of(who),
        may_publish=who.has(constants.PERM_PUBLISH),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    return row


def _scan_and_map(data: bytes, tz: str, categories: dict[str, uuid.UUID]) -> Mapped:
    """Pure and bounded: scanned, then mapped, within ``IMPORT_PARSE_SECONDS`` (over it:
    ``too_complex``). Runs in a thread, off the event loop."""
    deadline = time.monotonic() + constants.IMPORT_PARSE_SECONDS
    return map_calendar(scan(data).events, calendar_tz=tz, categories=categories, deadline=deadline)


async def _categories(db: Any, default_locale: str) -> dict[str, uuid.UUID]:
    rows = (
        await db.execute(select(Category).where(Category.tenant_id == bound_tenant()))  # type: ignore[arg-type]
    ).scalars()
    found: dict[str, uuid.UUID] = {}
    for row in rows:
        name = (row.names or {}).get(default_locale)
        if isinstance(name, str) and name.strip():
            found.setdefault(name.strip().lower(), row.id)
    return found


async def _fail(
    db: Any, imp: EventImport, owner: str, now: datetime, failure: ImportFailure
) -> str:
    await fenced(
        db,
        tenant_id=bound_tenant(),
        import_id=imp.id,  # type: ignore[arg-type]
        owner=owner,
        values={
            "status": "failed",
            "error_code": failure.code,
            "source": None,
            "finished_at": now,
            "updated_at": now,
            "lease_owner": None,
            "lease_until": None,
        },
    )
    logger.info("events: import %s failed (%s, bound %s)", imp.id, failure.code, failure.bound)
    return "failed"


async def parse_step(
    db: Any, imp: EventImport, *, owner: str, now: datetime, locales: tuple[str, ...]
) -> Literal["staged", "failed"]:
    """Stage the items of an import this ``owner`` has claimed (``parsing``). Writes through
    ``db`` without committing; ``LeaseLost`` (nothing written) when the claim is gone."""
    calendar = (
        await db.execute(
            select(Calendar).where(
                Calendar.id == imp.calendar_id,  # type: ignore[arg-type]
                Calendar.tenant_id == bound_tenant(),  # type: ignore[arg-type]
            )
        )
    ).scalar_one_or_none()
    if calendar is None or imp.source is None:
        return await _fail(db, imp, owner, now, ImportFailure("import_failed", "calendar"))  # type: ignore[return-value]
    categories = await _categories(db, locales[0])
    try:
        mapped = await asyncio.to_thread(
            _scan_and_map, imp.source, timezones.effective(calendar.default_timezone), categories
        )
    except ImportFailure as failure:
        return await _fail(db, imp, owner, now, failure)  # type: ignore[return-value]
    except Exception as exc:  # a bug in mapping fails this file, never the worker (class only)
        logger.warning("events: import %s could not be mapped (%s)", imp.id, type(exc).__name__)
        return await _fail(db, imp, owner, now, ImportFailure("import_failed", "mapping"))  # type: ignore[return-value]
    uids = [i.uid for i in mapped.items if i.event is not None]
    existing = await existing_uids(db, imp.calendar_id, uids)
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    rows = [item_row(imp, n, item, existing) for n, item in enumerate(mapped.items, start=1)]
    deadline = time.monotonic() + constants.IMPORT_PARSE_SECONDS
    actor, probed = imp.created_by, False
    for row in rows:
        # An update that the write would find nothing to change previews as such; past the time
        # budget the rest stay "update" (the apply step still says "unchanged").
        if row.verdict == "update" and time.monotonic() < deadline:
            probed = True
            if await is_unchanged(db, actor, row, locales):
                row.verdict = "unchanged"
    if probed:
        await db.refresh(imp)  # the probes' rollbacks expired it
    for row in rows:
        counts[row.verdict] += 1
        reasons.update([row.reason] if row.reason else [])
        reasons.update(row.notes)
    for start in range(0, len(rows), constants.IMPORT_ITEM_CHUNK):
        db.add_all(rows[start : start + constants.IMPORT_ITEM_CHUNK])
        await db.flush()
    await fenced(
        db,
        tenant_id=bound_tenant(),
        import_id=imp.id,  # type: ignore[arg-type]
        owner=owner,
        values={
            "status": "staged",
            "source": None,
            "total": len(rows),
            "counts": {k: counts.get(k, 0) for k in constants.ITEM_VERDICTS},
            "reasons": dict(reasons.most_common(constants.IMPORT_KEEP_REASONS)),
            "dropped": dict(mapped.dropped),
            "updated_at": now,
            "lease_owner": None,
            "lease_until": None,
        },
    )
    return "staged"
