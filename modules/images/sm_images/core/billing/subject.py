"""Who an image's billing bills (#284).

In billing's ``tenant`` mode the subject is the tenant. In ``user`` mode it is
``user:<collection.owner_id>``: one image always has one payer, so its storage
hold can be swapped, grown and released under one subject for its whole life.

The subject is **recorded** when a hold is taken (``BillingOp.subject``,
``Image.storage_subject``; ``NULL`` means the row's ``tenant_id``, see
:func:`held_under`) and replayed afterwards. Only a brand-new hold or a one-shot
charge derives one here, so a mode switch or an ownership change never sends a
call to a subject that does not hold the key.

The mode is ``app.state`` in the web process (:func:`app_mode`) and billing's
DB-backed setting in a worker (:func:`worker_mode`); a ``Runtime`` carries
whichever applies, and with no runtime bound :func:`runtime_mode` falls back to
the stored setting, never to ``tenant``. Billing stays optional: without it the
mode is ``tenant`` and ``sm_billing`` is never imported.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from simple_module_db import finalize_session

from sm_images.core import billing

__all__ = [
    "TENANT",
    "USER",
    "app_mode",
    "for_app",
    "held_under",
    "image_subject",
    "owner_subject",
    "owner_subject_in",
    "reset_unbillable_log",
    "runtime_mode",
    "user_exists",
    "user_subject",
    "worker_mode",
]

TENANT: Final = "tenant"
USER: Final = "user"

logger = logging.getLogger(__name__)
_warned: set[uuid.UUID | None] = set()


def app_mode(app: Any) -> str:
    """The web process's mode: ``app.state``, as billing's boot set it."""
    if not billing.billing_installed():
        return TENANT
    from sm_billing.contracts import current_subject_mode

    return current_subject_mode(app)


def worker_mode() -> str:
    """The worker's mode (DB-backed, cached about 30 s). A failed read raises,
    so the step is retried: it never falls back to billing ``default``."""
    if not billing.billing_installed():
        return TENANT
    from sm_billing.contracts import worker_subject_mode

    return worker_subject_mode()


def runtime_mode() -> str:
    """The current runtime's mode. With none bound (a CLI, a worker that never
    called ``use_runtime``) billing's stored setting (:func:`worker_mode`), so
    such a caller never bills the tenant in ``user`` mode; ``tenant`` without
    billing."""
    from sm_images.pipeline.runtime import current_runtime

    runtime = current_runtime()
    return worker_mode() if runtime is None else runtime.billing_mode()


def held_under(tenant: str, recorded: str | None) -> str:
    """The subject a hold was taken under: the recorded one, ``NULL`` meaning
    the row's tenant (every row before #284)."""
    return recorded or tenant


def reset_unbillable_log() -> None:
    _warned.clear()


def _unbillable(collection_id: uuid.UUID | None) -> None:
    if collection_id in _warned:
        return
    _warned.add(collection_id)
    logger.warning("images.billing.owner_unbillable collection=%s", collection_id)


def user_subject(owner_id: str | None) -> str | None:
    """``user:<owner>`` as billing spells it; ``None`` for an owner no user can be
    (missing, or not a UUID). Pure: no lookup, no log."""
    from sm_billing.contracts import subject_for_user

    if owner_id is None:
        return None
    try:
        return subject_for_user(owner_id)
    except ValueError:
        return None


def image_subject(
    tenant: str, owner_id: str | None, mode: str, *, collection_id: uuid.UUID | None = None
) -> str:
    """The subject for a collection owned by ``owner_id`` (pure, no lookup).
    A missing or non-UUID owner bills the tenant, logged once per collection."""
    if mode != USER:
        return tenant
    who = user_subject(owner_id)
    if who is None:
        _unbillable(collection_id)
        return tenant
    return who


async def user_exists(db: Any, subject: str) -> bool:
    """Whether billing knows ``subject`` (the seam tests patch)."""
    from sm_billing.contracts import subject_exists

    return await subject_exists(db, subject)


async def owner_subject(db: Any, tenant: str, collection: Any, mode: str) -> str:
    """:func:`image_subject`, falling back to the tenant when the owner's user
    row is gone. Tenant mode runs no query."""
    who = image_subject(tenant, collection.owner_id, mode, collection_id=collection.id)
    if who == tenant or await user_exists(db, who):
        return who
    _unbillable(collection.id)
    return tenant


async def owner_subject_in(factory: Any, tenant: str, collection: Any, mode: str) -> str:
    """:func:`owner_subject` in a short read session of its own, for callers
    whose session may hold (or soon take) the SQLite writer lock. Tenant mode
    opens no session."""
    if mode != USER:
        return tenant
    async with factory() as db:
        who = await owner_subject(db, tenant, collection, mode)
        await finalize_session(db)
    return who


async def for_app(app: Any, factory: Any, tenant: str, collection: Any) -> str:
    """:func:`owner_subject_in` in the web process's mode (``app.state``)."""
    return await owner_subject_in(factory, tenant, collection, app_mode(app))
