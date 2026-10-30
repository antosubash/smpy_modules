"""Whether the user a background run was started by still holds the right it
was started under: the one decision behind every worker's re-check.

Imports and regroups (an ``edit``: owner, an edit share or ``images.manage``)
and whole-collection restarts and prompt runs (owner or ``images.manage``;
shares never) record ``run_as`` and ``access_basis`` when they are accepted,
and the worker asks :func:`holds_right` before each chunk. What still counts,
from a worker:

* ``run_as`` owns the collection;
* with ``shares``, an active (unexpired) edit share names them - the same
  ``EXISTS`` the access policy builds (``sharing.policy.share_exists_for``);
* the right came from ``images.manage`` (:data:`MANAGE`) and the user still
  exists, is active and (multi-tenant) still a member of the tenant
  (``imports.manage_right.manager_active``; the permission itself is not
  re-resolved in a worker, that module says why).

A run with no ``run_as`` (made by code, or before this existed) is not
checked, and neither is a collection that is gone: the run's own reads stop it.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sharing.policy import share_exists_for
from simple_module_core.resources import ACTION_EDIT, ResourcePrincipal
from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.access import COLLECTION_RESOURCE
from sm_images.imports.manage_right import manager_active
from sm_images.models import Collection
from sm_images.pipeline.runtime import Runtime

__all__ = ["MANAGE", "OWNER", "SHARE", "holds_right", "owner_or_manage_basis", "shared_edit"]

OWNER: Final = "owner"
SHARE: Final = "share"
MANAGE: Final = "manage"

_SHARES = share_exists_for(COLLECTION_RESOURCE, Collection.id)


def shared_edit(user_id: str, collection_id: uuid.UUID) -> Any:
    clause = _SHARES(ResourcePrincipal(user_id=user_id), ACTION_EDIT)
    return select(Collection.id).where(Collection.id == collection_id, clause)


def owner_or_manage_basis(who: ResourcePrincipal, collection: Collection) -> str:
    """The basis of a run only the owner or a manager may start."""
    return OWNER if who.user_id is not None and collection.owner_id == who.user_id else MANAGE


async def holds_right(
    runtime: Runtime,
    tenant: str,
    collection_id: uuid.UUID,
    run_as: str | None,
    basis: str | None,
    *,
    shares: bool = True,
) -> bool:
    """Whether *run_as* still holds the right on *collection_id* (see module)."""
    if run_as is None:
        return True
    stmt = select(Collection.owner_id).where(
        Collection.id == collection_id, Collection.tenant_id == tenant
    )
    async with runtime.session_factory() as db:
        owner = (await db.execute(stmt)).scalar_one_or_none()
        shared = None
        if shares and owner is not None and owner != run_as:
            shared = (await db.execute(shared_edit(run_as, collection_id))).first()
        await finalize_session(db)
    if owner is None or owner == run_as or shared is not None:
        return True
    if basis == MANAGE:
        return await manager_active(runtime, tenant, run_as)
    return False
