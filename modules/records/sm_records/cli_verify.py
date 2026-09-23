"""``python -m sm_records.cli reindex --verify`` — does the reduce index agree?

Phase 5 §5.2's third leg, and the honest answer to design §7.5's objection: a
maintained aggregate is a second source of truth, so the question is not
whether it can drift but whether anyone would find out. This recomputes every
registered spec from the **records** — the only source of truth there is — and
reports every ``(type, key, group)`` whose stored row disagrees.

It writes nothing. Repairing silently would make the drift undetectable again
one command later; the repair is ``reindex``, which says what it did.

Exit code 1 on drift and 0 on a clean run, so it is usable as a deploy gate or
a cron check without parsing the output. In a repo with no queue that is the
form a scheduled integrity check has to take.

Split from :mod:`sm_records.cli` for the 300-line cap, along the same seam
``cli_io`` is split on: that file parses and dispatches, this one owns a
command's work.

**Per tenant** (tenancy design §A.5). The types to check are listed with one
cross-tenant read. They are then verified tenant by tenant, each inside
``tenant_scope`` on a session of its own. ``--type`` names a key in one
tenant (``--tenant``, or ``default``). ``--tenant`` alone narrows the run to
that tenant.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from sm_records._cross_tenant import read_all
from sm_records.index.reduce import reduce_specs
from sm_records.index.reduce_rebuild import verify_type
from sm_records.models import RecordType
from sm_records.settings import RecordsSettings
from sm_records.tenancy import DEFAULT_TENANT, tenant_scope


async def _types_by_tenant(db_state, type_key: str | None, tenant: str | None) -> dict[str, list]:
    """``{tenant: [type id, ...]}`` to verify, read across tenants."""
    stmt = select(RecordType.tenant_id, RecordType.id).order_by(RecordType.tenant_id, RecordType.id)
    if type_key is not None:
        tenant = tenant or DEFAULT_TENANT
        stmt = stmt.where(RecordType.key == type_key)
    if tenant is not None:
        stmt = stmt.where(RecordType.tenant_id == tenant)
    async with db_state.session_factory() as session:
        rows = (await read_all(session, stmt)).all()
    if type_key is not None and not rows:
        raise SystemExit(f"no record type with key {type_key!r} in tenant {tenant!r}")
    out: dict[str, list] = defaultdict(list)
    for owner, type_id in rows:
        out[str(owner)].append(int(type_id))
    return dict(out)


async def verify(
    db_state, type_key: str | None, *, settings: RecordsSettings, tenant: str | None = None
) -> int:
    """Recompute and compare. Returns the number of drifting groups.

    A host with no spec registered is reported as such and is clean — that is
    the "inert when unused" property stated out loud rather than a silent zero
    that could equally mean "nothing checked".
    """
    if not reduce_specs():
        print("records verify: no reduce specs registered — nothing to check")
        return 0
    total = checked = 0
    for owner, type_ids in (await _types_by_tenant(db_state, type_key, tenant)).items():
        with tenant_scope(owner):
            async with db_state.session_factory() as session:
                stmt = select(RecordType).where(RecordType.id.in_(type_ids))
                for rtype in (await session.execute(stmt)).scalars().all():
                    drifts = await verify_type(
                        session, rtype, batch_size=settings.reindex_batch_size
                    )
                    for drift in drifts:
                        print(f"records verify: DRIFT {owner}/{drift.describe()}")
                    total += len(drifts)
                    checked += 1
    if total:
        print(
            f"records verify: {total} group(s) disagree — run "
            "`python -m sm_records.cli reindex --tenant TENANT --type KEY` to rebuild"
        )
    else:
        print(f"records verify: clean across {checked} type(s)")
    return total
