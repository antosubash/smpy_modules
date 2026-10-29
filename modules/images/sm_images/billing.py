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

1. :func:`reserve` (a ``held`` hold) *before* the caller's transaction first
   writes. A refusal is :class:`StorageQuotaExceeded`. Each attempt reserves
   under a key of its own, so it never shares - and never releases - another
   attempt's hold.
2. The caller records the hold id on the image and writes the settlement -
   ``commit`` the new hold, then ``release`` the old one - to the durable
   outbox in the same transaction (:mod:`sm_images.billing_ops`). A rollback
   discards both, and the ``held`` hold lapses at its TTL.

This module is the thin seam to billing; settlement lives in the outbox.

**Fail closed.** An installed billing that cannot meter (no ``usage_meter``,
or a broken import) raises: images never stores for free because billing
failed to load. Workers have no app, so the hold calls go through billing's
``usage_meter(session_factory)`` everywhere (one code path, as ``sm_ai``'s
``consume_requests``). Only the advisory :func:`check` reads the web
process's ``app.state.billing_usage``, whose meter registry knows the gauge.
"""

from __future__ import annotations

import importlib
import uuid
from functools import partial
from importlib.util import find_spec
from typing import Any

from simple_module_db.callbacks import register_on_commit

from sm_images import constants
from sm_images.errors import StorageQuotaExceeded

__all__ = [
    "billing_installed",
    "check",
    "extend",
    "factory_of",
    "hold_key",
    "on_commit",
    "register_meter",
    "reserve",
    "storage_meter",
]

METER = constants.METER_STORAGE
SOURCE = "images:storage"
FULL = "The plan's image storage is used up"


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


def hold_key(image_id: uuid.UUID | str, attempt: str | int) -> str:
    """The idempotency key of one hold: an image and the attempt that took it
    (a fresh nonce per attempt; a rehold names its outbox op)."""
    return f"images:{image_id}:storage:{attempt}"


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


async def reserve(
    session_factory: Any, tenant: str, qty: int, key: str, *, ttl: int | None = None
) -> Any:
    """Hold ``qty`` bytes (``held``, for ``ttl`` seconds or billing's default);
    billing's ``Hold`` (``id``, ``expires_at``), or ``None`` without billing.
    :class:`StorageQuotaExceeded` when it does not fit - or when the key's hold
    was since released (a key is never reused)."""
    meter = storage_meter(session_factory)
    if meter is None or qty < 1:
        return None
    outcome = await meter.reserve(tenant, METER, int(qty), key, source=SOURCE, ttl=ttl)
    if not outcome.ok:
        raise StorageQuotaExceeded(FULL)
    return outcome


async def extend(session_factory: Any, hold_id: str, ttl: int) -> Any:
    """Push a ``held`` hold's expiry to ``ttl`` seconds from now (billing's
    ``Hold``); ``HoldExpired`` once it lapsed."""
    meter = storage_meter(session_factory)
    return None if meter is None else await meter.extend(hold_id, ttl)


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
