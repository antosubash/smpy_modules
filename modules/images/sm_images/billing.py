"""Storage metering: the ``images.storage_bytes`` gauge (plan decision 10).

Billing is optional. Without it nothing here does anything and storage is
unlimited; ``Image.storage_bytes`` is kept by the callers either way.

**One committed hold per image**, sized to the sum of its objects (original,
display copy, renditions) and named by ``Image.storage_hold_id``. Every hold
images takes comes from billing's atomic :func:`swap`: the new hold is
committed and the image's old one released in **one** billing transaction,
with the quota checked on the net delta. So no images hold is ever ``held``
(nothing lapses), and replacing an image's hold never leaves it counted twice
or by nothing. Ingest swaps from no hold (a plain reserve and commit).

**Every billing write is its own short transaction** (billing finishes each
with ``finalize_session``), so none may run while the caller's session holds a
write lock - on file-backed SQLite it would wait on that lock and fail. The
swap is therefore driven by a durable op row (:mod:`sm_images.billing_ops`):
op row, then billing, then the image row, each its own transaction.

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
from datetime import datetime
from functools import partial
from importlib.util import find_spec
from typing import Any

from simple_module_db.callbacks import register_on_commit

from sm_images import constants
from sm_images.errors import StorageQuotaExceeded

__all__ = [
    "KeyClosed",
    "SwapExpired",
    "billing_installed",
    "check",
    "close_key",
    "factory_of",
    "held_by",
    "hold_key",
    "on_commit",
    "register_meter",
    "storage_meter",
    "swap",
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
    """The idempotency key of one swap: an image and the attempt that asked."""
    return f"images:{image_id}:storage:{attempt}"


async def check(app: Any, tenant: str, qty: int) -> None:
    """Refuse up front (402) what would not fit the gauge now. Advisory: the
    swap taken afterwards is the enforcement. Billing not running in this
    process (as ``RequiresQuota`` answers then), or nothing to store → no-op."""
    usage = getattr(app.state, constants.BILLING_USAGE_ATTR, None)
    if usage is None or qty < 1:
        return
    outcome = await usage.check(tenant, METER, int(qty))
    if not outcome.ok:
        raise StorageQuotaExceeded(FULL)


class SwapExpired(Exception):  # noqa: N818 - reads as the condition
    """Billing refused the swap: it arrived after its op's deadline."""


class KeyClosed(SwapExpired):
    """Billing refused the swap: its key was closed (``close_key``) - the op it
    belongs to was finished without it. Nothing changed, as for an expiry."""


async def swap(
    session_factory: Any,
    tenant: str,
    old: str | None,
    qty: int,
    key: str,
    meter: Any = None,
    *,
    not_after: datetime,
) -> Any:
    """Billing's atomic swap: a committed hold of ``qty`` bytes in place of
    ``old`` (billing's ``Hold``), or ``None`` without billing (or nothing to
    hold). :class:`StorageQuotaExceeded` when the net delta does not fit -
    ``old`` then still counts; :class:`SwapExpired` when the call reached
    billing after ``not_after``, :class:`KeyClosed` when its key was closed
    (nothing changed). A replayed ``key`` returns the same outcome; every
    outcome is final for its key."""
    meter = meter or storage_meter(session_factory)
    if meter is None or qty < 1:
        return None
    outcome = await meter.swap(
        tenant, METER, old, int(qty), key, source=SOURCE, not_after=not_after
    )
    kind = type(outcome).__name__
    if kind == "Closed":
        raise KeyClosed(key)
    if kind == "Expired":
        raise SwapExpired(key)
    if kind != "Hold":  # Exceeded: refused by the limit
        raise StorageQuotaExceeded(FULL)
    return outcome


async def close_key(session_factory: Any, tenant: str, key: str, meter: Any = None) -> Any:
    """The terminal outcome of the swap under ``key`` (billing's ``close_key``):
    its ``Hold``, ``Refused``, ``Expired``, or ``Closed`` - committed now, so no
    call under the key will ever write. Waits for a swap in flight. ``None``
    without billing. Raises when billing cannot answer: the caller's op must
    then stay unfinished, to be retried."""
    meter = meter or storage_meter(session_factory)
    if meter is None:
        return None
    return await meter.close_key(tenant, METER, key)


def held_by(outcome: Any) -> str | None:
    """The hold a key's outcome made: a ``Hold``'s id, never anything else's."""
    return outcome.id if type(outcome).__name__ == "Hold" else None


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
