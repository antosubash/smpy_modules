"""Is the manager a job runs for still around? Asked by a worker, with no request.

A job accepted on an ``images.manage`` right (``imports.access``) is **not**
re-resolved against that permission in a worker. The framework resolves
permissions per request (grant sources take the ``Request``; the role map,
code-mapped roles included, lives in the registry only the app builds), and a
worker reading the grant tables itself would disagree with it. So the worker
checks only that the user it runs for:

* still has a row in ``users_user`` (deleted users are gone);
* is active - ``is_active`` and not ``disabled_at``;
* on a multi-tenant host (any tenant but :data:`~sm_images.tenancy.DEFAULT_TENANT`),
  is still a member of the job's tenant (``tenants_membership``).

It **fails closed**: a missing row, an unreadable table, a module that is not
installed or an id that is not a uuid all answer ``False``, and the job is
cancelled.

**Accepted residual:** a manager who keeps their account and membership but
loses ``images.manage`` keeps running the jobs they started until they
finish - like any other background work in the framework, which acts on
what was authorised when it was queued.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from sm_images.pipeline.runtime import Runtime
from sm_images.tenancy import DEFAULT_TENANT

__all__ = ["manager_active"]

logger = logging.getLogger(__name__)


async def _first(runtime: Runtime, stmt: Any) -> Any:
    """``stmt``'s first row, in a session of its own; ``None`` when unreadable."""
    try:
        async with runtime.session_factory() as db:
            row = (await db.execute(stmt)).first()
            await finalize_session(db)
        return row
    except SQLAlchemyError:
        logger.warning("images.import.manager_unreadable", exc_info=True)
        return None


async def _active(runtime: Runtime, uid: uuid.UUID) -> bool:
    try:
        from users.models.user import User
    except ImportError:
        return False
    stmt = select(User.is_active, User.disabled_at).where(User.id == uid)
    row = await _first(runtime, stmt)
    return row is not None and bool(row[0]) and row[1] is None


async def _member(runtime: Runtime, tenant: str, user_id: str) -> bool:
    if tenant == DEFAULT_TENANT:
        return True  # a single-tenant host: everyone is a member
    try:
        from tenants.models import Membership
    except ImportError:
        return False
    stmt = select(Membership.id).where(
        Membership.tenant_id == tenant, Membership.user_id == user_id
    )
    return await _first(runtime, stmt) is not None


async def manager_active(runtime: Runtime, tenant: str, user_id: str) -> bool:
    """Whether ``user_id`` still exists, is active and belongs to ``tenant``."""
    try:
        uid = uuid.UUID(str(user_id))
    except ValueError:
        return False
    return await _active(runtime, uid) and await _member(runtime, tenant, str(user_id))
