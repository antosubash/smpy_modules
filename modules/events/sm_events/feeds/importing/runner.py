"""One slice of an import: claim, then parse or apply, in leased resumable batches (Rulings 21, 28).

A slice is one call: it **claims** the import for a fresh owner (:func:`~.fence.claim`):
``gone`` when there is no such import in the tenant or it is in no claimable state, ``busy`` when
someone holds a live lease. An ``uploaded`` import is **parsed** (one step, in one transaction,
:func:`~.staging.parse_step`). A ``queued``/``running`` one is **applied** in batches of
``IMPORT_APPLY_BATCH`` items still to do, in ``seq`` order, while the slice lasts: each batch is
:func:`~.apply.apply_batch` and the fenced counter update (which renews the lease) in one
transaction. When fewer than a batch is left the same transaction completes the import
(``done``); out of time, a fenced release and ``more``, and the next slice claims at once.

**Tenant.** The slice runs under ``tenant_scope(tenant_id)`` and nothing else: the caller's own
tenant (a request, a platform pass) is left first, so the rows written are the import's tenant's
whatever was bound. An id that is no import of that tenant is ``gone``.

**Rights.** A slice first checks that the grants stored at apply have not passed ``rights_until``
(``IMPORT_GRANTS_TTL``, one hour): later it writes nothing and ends ``rights_expired``. With an
``importer`` (an app is present: the eager path, ``launch.launch``) it then asks who the importer
is now and applies the narrower of that and the stored grants; an importer who is gone ends the
import ``importer_gone`` with the remaining items untouched. A Celery worker builds no app (no
user directory; upstream simple_module_python #1005), so it passes none and relies on the stored
grants within that hour plus the per-item checks (share, ownership, trash, lock).

**Failures.** Every write after the claim is fenced; a lost lease rolls back and answers
``busy``. A calendar that was trashed meanwhile, or any other exception, is recorded as ``failed``
(``import_failed``, a code only), logged by class name, and the slice answers ``done``: the row
says why. A crash (the process dies) leaves the lease to run out; the janitor relaunches.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from simple_module_core.resources import ResourcePrincipal
from simple_module_db import finalize_session, no_tenant
from sqlalchemy import select

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.errors import ImportFailure
from sm_events.core.tenancy import tenant_scope, valid_tenant
from sm_events.feeds.importing.apply import BatchResult, apply_batch
from sm_events.feeds.importing.fence import LeaseLost, claim, fenced
from sm_events.feeds.importing.staging import parse_step
from sm_events.models import Calendar, EventImport, EventImportItem

__all__ = ["SliceResult", "run_import_async"]

logger = logging.getLogger(__name__)
SliceResult = Literal["done", "more", "busy", "gone"]


Importer = Callable[[str, str], Awaitable[ResourcePrincipal | None]]
"""``(tenant_id, user_id)`` to the user's permissions *now* (``None``: gone, inactive, not a
member). Needs an app (the user directory), so a worker, which builds none, passes ``None``."""


class _Slice:
    def __init__(self, factory: Any, tenant_id: str, import_id: int, locales, now) -> None:
        self.factory, self.tenant_id, self.import_id = factory, tenant_id, import_id
        self.locales, self.now = locales, now
        self.owner = str(uuid.uuid4())
        self.grants: list[str] | None = None
        """The importer's permissions for this slice: the stored ones narrowed by a fresh answer."""

    async def narrow(self, importer: Importer) -> None:
        """Ask who the importer is *now* and keep what both the stored grants and the fresh
        answer allow. ``importer_gone`` ends the import: nobody to write as."""
        async with self.factory() as db:
            imp = await self._load(db)
            stored = ResourcePrincipal(imp.created_by, frozenset(imp.grants or ()))
            now = await importer(self.tenant_id, imp.created_by)
            await finalize_session(db)
        if now is None:
            raise ImportFailure(constants.IMPORTER_GONE, "importer")
        self.grants = [p for p in constants.PERMISSIONS if stored.has(p) and now.has(p)]

    async def check_rights_window(self) -> None:
        """Rights captured at apply are valid until ``rights_until``; later nothing is written."""
        async with self.factory() as db:
            until = (await self._load(db)).rights_until
        if until is None or self.now() > until.replace(tzinfo=until.tzinfo or UTC):
            raise ImportFailure("rights_expired", "ttl")

    async def fence(self, db: Any, values: dict[str, Any]) -> None:
        await fenced(
            db, tenant_id=self.tenant_id, import_id=self.import_id, owner=self.owner, values=values
        )

    async def _load(self, db: Any) -> EventImport:
        stmt = (
            select(EventImport)
            .where(EventImport.id == self.import_id, EventImport.tenant_id == self.tenant_id)  # type: ignore[arg-type]
            .execution_options(populate_existing=True)
        )
        return (await db.execute(stmt)).scalar_one()

    async def claim(self):
        async with self.factory() as db:
            answer = await claim(
                db,
                tenant_id=self.tenant_id,
                import_id=self.import_id,
                owner=self.owner,
                now=self.now(),
            )
            await finalize_session(db)
            return answer

    async def parse(self) -> None:
        async with self.factory() as db:
            await parse_step(
                db, await self._load(db), owner=self.owner, now=self.now(), locales=self.locales
            )
            await finalize_session(db)

    async def batch(self) -> bool:
        """One batch (completing the import when it was the last); whether it is done."""
        async with self.factory() as db:
            imp = await self._load(db)
            now = self.now()
            live = (
                await db.execute(
                    select(Calendar.id).where(
                        Calendar.id == imp.calendar_id,  # type: ignore[arg-type]
                        Calendar.tenant_id == self.tenant_id,  # type: ignore[arg-type]
                    )
                )
            ).scalar_one_or_none()
            if live is None:
                raise ImportFailure("import_failed", "calendar")
            items = list(
                (
                    await db.execute(
                        select(EventImportItem)
                        .where(
                            EventImportItem.tenant_id == self.tenant_id,  # type: ignore[arg-type]
                            EventImportItem.import_id == self.import_id,  # type: ignore[arg-type]
                            EventImportItem.outcome.is_(None),  # type: ignore[union-attr]
                        )
                        .order_by(EventImportItem.seq)
                        .limit(constants.IMPORT_APPLY_BATCH)
                    )
                ).scalars()
            )
            if self.grants is not None:
                imp.grants = self.grants  # in memory only: apply_batch detaches the row
            result = BatchResult()
            if items:
                result = await apply_batch(db, imp, items, locales=self.locales, now=now)
            last = len(items) < constants.IMPORT_APPLY_BATCH
            await self.fence(db, _values(result, now, last))
            await finalize_session(db)
            return last

    async def release(self) -> None:
        async with self.factory() as db:
            await self.fence(db, {"lease_owner": None, "lease_until": self.now()})
            await finalize_session(db)

    async def fail(self, code: str) -> bool:
        """The fenced failure write in a fresh session; whether it matched."""
        now = self.now()
        values = {
            "status": "failed",
            "error_code": code,
            "source": None,
            "finished_at": now,
            "updated_at": now,
            "lease_owner": None,
            "lease_until": None,
        }
        async with self.factory() as db:
            try:
                await self.fence(db, values)
            except LeaseLost:
                return False
            await finalize_session(db)
            return True


def _values(result: BatchResult, now: datetime, last: bool) -> dict[str, Any]:
    table = EventImport.__table__
    values: dict[str, Any] = {
        "processed": table.c.processed + result.processed,
        "created": table.c.created + result.created,
        "updated": table.c.updated + result.updated,
        "unchanged": table.c.unchanged + result.unchanged,
        "skipped": table.c.skipped + result.skipped,
        "failed": table.c.failed + result.failed,
        "updated_at": now,
        "lease_until": now + constants.IMPORT_LEASE,
    }
    if last:
        values.update(
            {"status": "done", "finished_at": now, "lease_owner": None, "lease_until": None}
        )
    return values


async def _work(
    step: _Slice, slice_seconds: float, clock: Callable[[], float], importer: Importer | None
) -> SliceResult:
    won = await step.claim()
    if won.kind != "claimed":
        return won.kind
    if won.status == "parsing":
        if won.attempts > constants.IMPORT_PARSE_ATTEMPTS:  # it keeps killing its workers
            raise ImportFailure("too_complex", "attempts")
        await step.parse()
        return "done"
    await step.check_rights_window()
    if importer is not None:
        await step.narrow(importer)
    deadline = clock() + slice_seconds
    while not await step.batch():
        if clock() >= deadline:
            await step.release()
            return "more"
    return "done"


async def run_import_async(
    factory: Any,
    *,
    tenant_id: str,
    import_id: int,
    locales: tuple[str, ...],
    now: Callable[[], datetime] | None = None,
    clock: Callable[[], float] = time.monotonic,
    slice_seconds: float | None = None,
    importer: Importer | None = None,
) -> SliceResult:
    """One slice of the import ``import_id`` of ``tenant_id``."""
    if not valid_tenant(tenant_id):
        return "gone"
    seconds = constants.IMPORT_SLICE_SECONDS if slice_seconds is None else slice_seconds
    with no_tenant(), tenant_scope(tenant_id):
        step = _Slice(factory, tenant_id, import_id, locales, now or utcnow)
        failure = ""
        code = "import_failed"
        try:
            return await _work(step, seconds, clock, importer)
        except LeaseLost:
            logger.info("events: import %s lost its lease; nothing written", import_id)
            return "busy"
        except ImportFailure as exc:
            failure, code = type(exc).__name__, exc.code
        except Exception as exc:
            failure = type(exc).__name__
        # Outside the handler: nothing of the original exception is chained from here on.
        try:
            recorded = await step.fail(code)
        except Exception as exc:
            logger.error(
                "events: import %s failed: %s (recording it failed: %s)",
                import_id,
                failure,
                type(exc).__name__,
            )
            return "done"
        if not recorded:
            logger.info("events: import %s: %s after losing its lease", import_id, failure)
            return "busy"
        logger.warning("events: import %s failed: %s", import_id, failure)
        return "done"
