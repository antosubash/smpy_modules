"""Purging a collection forgets its share rows (simple_module_python#683).

The purge calls ``sharing.contracts.forget_resource`` in its own session, under
the tenant the janitor bound: only the purged collection's ``images.collection``
shares in that tenant go; a live collection's, another tenant's and another
resource type's rows with the same id stay.
"""

from __future__ import annotations

import pytest
from sharing.models import ResourceShare
from sharing.policy import canonical_id
from simple_module_db import all_tenants, tenant_context
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.models import Collection
from sqlalchemy import select

from tests.jobs.test_janitor import NOW, OLD
from tests.support.access import share
from tests.support.pipeline import use_steps

T = DEFAULT_TENANT
OTHER = "other-tenant"


@pytest.fixture(autouse=True)
def _steps():
    use_steps()


async def _seed(pipe, tenant: str, *rows: ResourceShare) -> None:
    with tenant_context(tenant):
        async with pipe.db_state.session_factory() as s:
            s.add_all(rows)
            await s.commit()


async def _shares(pipe) -> set[tuple[str, str, str, str]]:
    with all_tenants():
        async with pipe.db_state.session_factory() as s:
            rows = await s.execute(
                select(
                    ResourceShare.tenant_id,
                    ResourceShare.resource_type,
                    ResourceShare.resource_id,
                    ResourceShare.subject_id,
                )
            )
            return {tuple(r) for r in rows}


async def test_purging_a_collection_forgets_only_its_own_shares(pipe):
    from sm_images.jobs.purge import purge_expired

    gone, live = await pipe.collection({}), await pipe.collection({})
    await pipe.image(gone)
    await _seed(pipe, T, share(gone, "vic", "view"), share(gone, "eddie", "edit"))
    await _seed(pipe, T, share(live, "vic", "view"))
    elsewhere = share(gone, "vic", "view")  # same id, another tenant's table rows
    other_type = share(gone, "sam", "view")
    other_type.resource_type = "other.thing"
    await _seed(pipe, OTHER, elsewhere)
    await _seed(pipe, T, other_type)
    await pipe.trash(Collection, gone.id, OLD)

    with tenant_context(T):  # as the janitor binds each tenant in turn
        async with pipe.db_state.session_factory() as db:
            report = await purge_expired(db, pipe.store, now=NOW, grace_days=7)
            await db.commit()

    assert report.collections == [gone.id]
    left = await _shares(pipe)
    gone_id, live_id = canonical_id(gone.id), canonical_id(live.id)
    assert {(t, rt, rid) for t, rt, rid, _ in left} == {
        (T, "images.collection", live_id),
        (OTHER, "images.collection", gone_id),
        (T, "other.thing", gone_id),
    }


async def test_a_dry_run_keeps_the_shares(pipe):
    from sm_images.jobs.purge import purge_expired

    coll = await pipe.collection({})
    await _seed(pipe, T, share(coll, "vic", "view"))
    await pipe.trash(Collection, coll.id, OLD)
    with tenant_context(T):
        async with pipe.db_state.session_factory() as db:
            await purge_expired(db, pipe.store, now=NOW, grace_days=7, dry_run=True)
    assert len(await _shares(pipe)) == 1
