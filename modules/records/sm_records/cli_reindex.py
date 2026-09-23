"""``python -m sm_records.cli reindex [--type KEY] [--tenant T] [--verify]``.

The recovery path for an index that is wrong (design doc §7.7, §8.9). Split
from :mod:`sm_records.cli` for the 300-line cap: that file parses and
dispatches, and this one owns the connection for the two reindex commands.
:mod:`sm_records.cli_verify` does the ``--verify`` work.

**Which tenants** (tenancy design §A.5):

* ``--type KEY`` looks ``KEY`` up in one tenant: ``--tenant``, or ``default``.
  A key names a type only within its tenant.
* Without ``--type``, every tenant's pending types are listed with one
  cross-tenant read. Each runs through
  :func:`~sm_records.services.reindex_runner.run_pending`, which binds that
  type's tenant on a session of its own. ``--tenant`` narrows the list to one
  tenant.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from sm_records._cross_tenant import read_all
from sm_records.cli_common import load_settings, open_db
from sm_records.models import RecordType
from sm_records.services.reindex_runner import run_pending
from sm_records.tenancy import DEFAULT_TENANT, tenant_scope

__all__ = ["force_pending", "reindex", "run_verify"]


async def _named_type(db_state, type_key: str, tenant: str) -> tuple[int, str, str]:
    """``(id, tenant, key)`` of ``type_key`` in ``tenant``, or a usage error."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as session:
            stmt = select(RecordType.id).where(
                RecordType.key == type_key, RecordType.tenant_id == tenant
            )
            type_id = (await session.execute(stmt)).scalar()
    if type_id is None:
        raise SystemExit(f"no record type with key {type_key!r} in tenant {tenant!r}")
    return int(type_id), tenant, type_key


async def _pending_types(db_state, tenant: str | None) -> list[tuple[int, str, str]]:
    """``(id, tenant, key)`` for every type with a marker set, in every tenant
    unless ``tenant`` narrows it. Filtered in Python, for the reason
    :func:`~sm_records.services.reindex_runner.pending_type_ids` gives."""
    stmt = select(
        RecordType.id, RecordType.tenant_id, RecordType.key, RecordType.reindex_pending
    ).order_by(RecordType.tenant_id, RecordType.key)
    if tenant is not None:
        stmt = stmt.where(RecordType.tenant_id == tenant)
    async with db_state.session_factory() as session:
        rows = (await read_all(session, stmt)).all()
    return [(int(i), str(t), str(k)) for i, t, k, pending in rows if pending]


async def reindex(database_url: str, type_key: str | None, tenant: str | None = None) -> int:
    """Run every pending rebuild (or one named type's) and print a summary.

    A type named explicitly is run even if nothing is pending: that is the
    "the index is wrong, rebuild it" case of §7.7, which is not driven by a
    marker. Without ``--type`` only the types carrying markers are visited,
    because walking every record of every type is not what an operator
    recovering one stuck field asked for.
    """
    db_state = open_db(database_url)
    try:
        settings = await load_settings(db_state)
        if type_key is not None:
            targets = [await _named_type(db_state, type_key, tenant or DEFAULT_TENANT)]
        else:
            targets = await _pending_types(db_state, tenant)
        if not targets:
            print("records reindex: nothing pending")
            return 0
        total = 0
        for type_id, owner, key in targets:
            count = await run_pending(db_state, type_id, settings=settings)
            total += count
            print(f"records reindex: {owner}/{key} — {count} record(s)")
        print(f"records reindex: {total} record(s) across {len(targets)} type(s)")
        return total
    finally:
        await db_state.engine.dispose()


def force_pending(database_url: str, type_key: str, tenant: str = DEFAULT_TENANT) -> None:
    """``--type`` on a type with no markers: mark the whole type, then run.

    Written as a marker rather than as a second code path through the runner,
    so the rebuild an operator triggers by hand is the identical operation a
    schema change triggers — including being resumable if this process dies
    halfway through it.
    """
    from sm_records.constants import REINDEX_ALL
    from sm_records.services._common import mark_written, utcnow

    async def run() -> None:
        db_state = open_db(database_url)
        try:
            with tenant_scope(tenant):
                async with db_state.session_factory() as session:
                    stmt = select(RecordType).where(
                        RecordType.key == type_key, RecordType.tenant_id == tenant
                    )
                    rtype = (await session.execute(stmt)).scalars().first()
                    if rtype is None:
                        raise SystemExit(
                            f"no record type with key {type_key!r} in tenant {tenant!r}"
                        )
                    pending = dict(rtype.reindex_pending or {})
                    pending.setdefault(REINDEX_ALL, utcnow().isoformat())
                    for raw in rtype.fields or []:
                        if raw.get("indexed"):
                            pending.setdefault(str(raw.get("key")), utcnow().isoformat())
                    rtype.reindex_pending = pending
                    session.add(rtype)
                    mark_written(session)
                    await session.commit()
        finally:
            await db_state.engine.dispose()

    asyncio.run(run())


async def run_verify(database_url: str, type_key: str | None, tenant: str | None = None) -> int:
    """``reindex --verify``: the connection, and :mod:`sm_records.cli_verify`
    for the work — the same division of labour :func:`reindex` has."""
    from sm_records import cli_verify

    db_state = open_db(database_url)
    try:
        settings = await load_settings(db_state)
        return await cli_verify.verify(db_state, type_key, settings=settings, tenant=tenant)
    finally:
        await db_state.engine.dispose()
