"""Storage metering: the ``images.storage_bytes`` gauge (plan decision 10).

Billing is optional. Without it nothing here does anything and storage is
unlimited; ``Image.storage_bytes`` is kept by the callers either way.

**One committed hold per image**, sized to the sum of its objects (original,
display copy, renditions) and named by ``Image.storage_hold_id``. Ingest holds
the original's size; a published display copy or rendition set takes a hold
for the new total and then releases the old one; the janitor releases the hold
of a hard-deleted image.

**Every billing write is its own short transaction** (billing finishes each
with ``finalize_session``), so none may run while the caller's session holds a
write lock - on file-backed SQLite it would wait on that lock and fail. Hence
the order every caller follows, the same as for object intents:

1. :func:`reserve` (a ``held`` hold with billing's TTL) *before* the caller's
   transaction first writes. A refusal is :class:`StorageQuotaExceeded`.
2. The caller records the hold id on the image in its transaction and queues
   :func:`settle` with :func:`on_commit`: after the commit the new hold is
   committed and the old one released.
3. A caller that does not keep the hold queues :func:`release` the same way.
   A rollback discards the queued call, and the ``held`` hold lapses at its TTL
   - capacity comes back by itself, never leaks.

**Fail closed.** An installed billing that cannot meter (no ``usage_meter``,
or a broken import) raises: images never stores for free because billing
failed to load. Workers have no app, so the hold calls go through billing's
``usage_meter(session_factory)`` everywhere (one code path, as ``sm_ai``'s
``consume_requests``). Only the advisory :func:`check` reads the web
process's ``app.state.billing_usage``, whose meter registry knows the gauge.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from collections.abc import Sequence
from functools import partial
from importlib.util import find_spec
from typing import Any

from simple_module_db.callbacks import register_on_commit

from sm_images import constants
from sm_images.errors import StorageQuotaExceeded

__all__ = [
    "StorageHold",
    "billing_installed",
    "check",
    "hold_key",
    "on_commit",
    "register_meter",
    "release",
    "release_storage",
    "reserve",
    "settle",
    "storage_meter",
]

logger = logging.getLogger(__name__)
METER = constants.METER_STORAGE
SOURCE = "images:storage"
FULL = "The plan's image storage is used up"

StorageHold = tuple[uuid.UUID, str | None, int]
"""``(image_id, storage_hold_id, storage_bytes)`` of a hard-deleted image."""


def register_meter(app: Any) -> bool:
    """Define the gauge on billing's registry, when billing is running."""
    registry = getattr(app.state, constants.BILLING_METERS_ATTR, None)
    if registry is None:
        return False
    registry.define(
        key=METER, kind="gauge", unit="bytes", label_key=constants.METER_STORAGE_LABEL_KEY
    )
    return True


def billing_installed() -> bool:
    """Whether ``sm_billing`` is installed at all: the only unmetered case."""
    try:
        return find_spec(constants.BILLING_PACKAGE) is not None
    except ModuleNotFoundError:
        return False


def storage_meter(session_factory: Any) -> Any:
    """Billing's ``UsageMeter`` over ``session_factory``; ``None`` without billing."""
    if not billing_installed():
        return None
    contract = importlib.import_module(constants.BILLING_USAGE_MODULE)  # errors propagate
    usage_meter = getattr(contract, "usage_meter", None)
    if usage_meter is None:  # installed, but cannot meter here: refuse, never store free
        raise RuntimeError("the installed billing has no usage_meter: storage cannot be metered")
    return usage_meter(session_factory)


def hold_key(image_id: uuid.UUID | str, generation: str | int) -> str:
    """The idempotency key of one hold: an image and its storage generation
    (``0`` at ingest, the attempt's nonce at a publication)."""
    return f"images:{image_id}:storage:{generation}"


async def check(app: Any, tenant: str, qty: int) -> None:
    """Refuse up front (402) what would not fit the gauge now. Advisory: the
    hold taken afterwards is the enforcement. Billing not running in this
    process (as ``RequiresQuota`` answers then), or nothing to store → no-op."""
    usage = getattr(app.state, constants.BILLING_USAGE_ATTR, None)
    if usage is None or qty < 1:
        return
    outcome = await usage.check(tenant, METER, int(qty))
    if not outcome.ok:
        raise StorageQuotaExceeded(FULL)


async def reserve(session_factory: Any, tenant: str, qty: int, key: str) -> str | None:
    """Hold ``qty`` bytes (``held``, billing's TTL); the hold id, or ``None``
    without billing. :class:`StorageQuotaExceeded` when it does not fit - or
    when the key's hold was since released (a key is never reused)."""
    meter = storage_meter(session_factory)
    if meter is None or qty < 1:
        return None
    outcome = await meter.reserve(tenant, METER, int(qty), key, source=SOURCE)
    if not outcome.ok:
        raise StorageQuotaExceeded(FULL)
    return outcome.id


async def settle(session_factory: Any, new: str | None, old: str | None) -> None:
    """Commit ``new``, then release ``old`` (decision 10's order). Runs after
    the caller's commit; a failure is logged, never raised - the row is durable.
    ``old`` is released even when ``new`` could not be committed: the gauge
    may then under-count this image, but capacity never leaks."""
    meter = storage_meter(session_factory)
    if meter is None:
        return
    if new is not None:
        try:
            await meter.commit(new)
        except Exception:
            logger.warning("images.billing.commit_failed hold=%s", new, exc_info=True)
    if old is not None and old != new:
        await release(session_factory, [old])


async def release(session_factory: Any, hold_ids: Sequence[str | None]) -> None:
    """Return each hold's capacity; best effort (a settled hold is a no-op)."""
    ids = [h for h in dict.fromkeys(hold_ids) if h]
    meter = storage_meter(session_factory) if ids else None
    if meter is None:
        return
    for hold_id in ids:
        try:
            await meter.release(hold_id)
        except Exception:
            logger.warning("images.billing.release_failed hold=%s", hold_id, exc_info=True)


def on_commit(db: Any, call: Any, *args: Any) -> None:
    """Run ``call(*args)`` after ``db`` commits (discarded on a rollback)."""
    register_on_commit(db, partial(call, *args))


def factory_of(db: Any, fallback: Any = None) -> Any:
    """The framework session factory behind ``db`` (or ``fallback``)."""
    from simple_module_db.session import SESSION_FACTORY_KEY

    found = getattr(db, "info", {}).get(SESSION_FACTORY_KEY)
    if found is not None:
        return found
    if fallback is not None:
        return fallback
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(db.bind, expire_on_commit=False)


async def release_storage(
    db: Any, holds: Sequence[StorageHold], session_factory: Any = None
) -> None:
    """The janitor's purge: release the hard-deleted images' holds once its
    transaction (objects already deleted, rows now deleted) commits."""
    ids = [hold for _, hold, _ in holds if hold]
    if ids:
        on_commit(db, release, factory_of(db, session_factory), ids)
