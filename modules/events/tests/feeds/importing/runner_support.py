"""Drive an import through the runner: stage a file, queue it, run slices, read the result."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.importing.runner import run_import_async
from sm_events.models import Event, EventImport, EventImportItem
from sqlalchemy import select, update

from tests.feeds.importing import corpus
from tests.feeds.importing.staging_support import make_import, seed

PUBLISHER = ("events.view", "events.manage", "events.publish")


async def stage(state: Any, data: bytes | None = None, *, tenant="default", calendar=None) -> tuple:
    """A calendar and an ``uploaded`` import of ``data`` in ``tenant``: ``(calendar, id)``."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            cals = await seed(db)
            target = calendar or cals["P"]
            imp = await make_import(db, target, data=data if data is not None else corpus.simple(3))
            await db.commit()
            return target, imp.id


async def run(state: Any, import_id: int, *, tenant="default", locales=("en",), **kw: Any) -> str:
    return await run_import_async(
        state.session_factory, tenant_id=tenant, import_id=import_id, locales=locales, **kw
    )


async def queue(
    state: Any,
    import_id: int,
    *,
    publish=False,
    grants=PUBLISHER,
    tenant="default",
    until: datetime | None = None,
) -> None:
    """What the apply endpoint does: ``staged`` becomes ``queued`` with the applier's rights."""
    table = EventImport.__table__
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            await db.execute(
                update(table)
                .where(table.c.id == import_id, table.c.tenant_id == tenant)
                .values(
                    status="queued",
                    publish=publish,
                    grants=list(grants),
                    rights_until=until or utcnow() + constants.IMPORT_GRANTS_TTL,
                    may_publish="events.publish" in grants,
                )
            )
            await db.commit()


async def read(state: Any, import_id: int, *, tenant="default"):
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            imp = (
                await db.execute(select(EventImport).where(EventImport.id == import_id))
            ).scalar_one_or_none()
            items = list(
                (
                    await db.execute(
                        select(EventImportItem)
                        .where(EventImportItem.import_id == import_id)
                        .order_by(EventImportItem.seq)
                    )
                ).scalars()
            )
            events = list((await db.execute(select(Event).order_by(Event.uid))).scalars())
            return imp, items, events


def app_for(state: Any, **settings: Any):
    """What ``launch`` reads from an app: the session factory and the content locales."""
    from sm_events.core.settings import EventsSettings

    return SimpleNamespace(
        state=SimpleNamespace(
            sm=SimpleNamespace(db=state),
            sm_events=SimpleNamespace(settings=EventsSettings(**settings)),
        )
    )


def importer_keeps_stored_rights(monkeypatch: Any) -> None:
    """For tests of something else: the importer is asked and answers with every permission, so
    the stored grants alone decide (the real check is tested through ``launch`` itself)."""
    from simple_module_core.resources import ResourcePrincipal
    from sm_events.feeds.importing import launch

    def check(_app: Any):
        async def ask(_tenant: str, user: str):
            return ResourcePrincipal(user, frozenset(constants.PERMISSIONS))

        return ask

    monkeypatch.setattr(launch, "importer_check", check)
