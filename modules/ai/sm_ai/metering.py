"""Usage metering: every AI request a consumer serves counts as ``ai.requests``.

Billing is optional for this module. Without it nothing is metered and
nothing is limited; with it, ``ai.requests`` is a per-period counter an
administrator limits per plan, and a request past the limit answers billing's
402 ``quota_exceeded``. The module never depends on billing in its
``pyproject``: the meter is registered through ``app.state.billing_meters``
(no import), and the dependency imports billing's ``RequiresQuota`` only when
the package is installed.

The base module serves no chat of its own (consumers own agents, prompts and
routes), so the consumer puts the dependency on the route that calls the
model::

    from sm_ai.contracts import RequiresAiRequest, resolve_model

    @router.post("/summarise", dependencies=[RequiresAiRequest()])
    async def summarise(...):
        result = await agent.run(text, model=resolve_model())

The charge is refunded only when the handler *raises*, so a provider error
must propagate (or be re-raised) rather than be turned into a returned error
response. A streaming response is charged when the handler returns it: an
error while the body streams is past the handler and refunds nothing.

Outside a request - a Celery worker - :func:`consume_requests` charges the
same meter (see its section below).
"""

from __future__ import annotations

import importlib
import os
import threading
from importlib.util import find_spec
from typing import Any

from fastapi import Depends, FastAPI

from sm_ai import constants

# The bound billing's validate.QTY_MAX enforces, repeated so an unmetered host
# rejects the same arguments a metered one does.
_QTY_MAX = 2**53


def _check_qty(qty: int) -> None:
    if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= _QTY_MAX:
        raise ValueError(f"qty must be an integer from 1 to {_QTY_MAX}")


def _installed(name: str) -> bool:
    """Whether module ``name`` is installed; only a *missing* module (or
    parent) is ``False`` - any other import error propagates."""
    try:
        return find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def register_meter(app: FastAPI) -> bool:
    """Define ``ai.requests`` on billing's registry, when billing is running.

    Called from ``AiModule.on_startup``. Billing creates the registry while the
    app is constructed, so it exists here whatever order the modules start in.
    """
    registry = getattr(app.state, constants.BILLING_METERS_ATTR, None)
    if registry is None:
        return False
    registry.define(
        key=constants.METER_REQUESTS,
        kind=constants.METER_KIND_COUNTER,
        unit=constants.METER_UNIT_COUNT,
        label_key=constants.METER_REQUESTS_LABEL_KEY,
    )
    return True


def billing_metering_installed() -> bool:
    """Whether a billing that meters is installed (it is optional, and a
    billing older than usage metering has no ``RequiresQuota``).

    ``find_spec`` of a dotted name imports its parents (``sm_billing``,
    ``sm_billing.metering``) when they exist — only an *installed* billing is
    ever imported. Only a missing module means "absent": any other import
    error in an installed billing propagates, rather than quietly turning
    metering off.
    """
    return _installed(constants.BILLING_QUOTA_MODULE)  # no sm_billing, or one without metering


async def _unmetered() -> None:
    return None


def RequiresAiRequest(qty: int = 1) -> Any:  # noqa: N802 - reads like RequiresQuota
    """Charge ``qty`` AI requests to the request's tenant before the handler runs.

    With billing installed this *is* billing's ``RequiresQuota("ai.requests")``
    — its 402 envelope, its refund on a raised handler, its
    ``Idempotency-Key`` replay rules, its tenant rule (single-tenant host:
    ``default``) — and with billing installed but not running it yields
    ``None``, as ``RequiresQuota`` does. Without billing (or with a billing
    older than metering) it is a no-op.
    """
    _check_qty(qty)
    if not billing_metering_installed():
        return Depends(_unmetered)
    from sm_billing.metering.deps import RequiresQuota

    return RequiresQuota(constants.METER_REQUESTS, qty)


# -- outside a request -------------------------------------------------------
# ``ai.requests`` charged where there is no request: :func:`consume_requests`.
#
# A Celery worker never builds the app, so ``RequiresAiRequest`` (a FastAPI
# dependency) and ``app.state.billing_usage`` are both out of reach there. This
# calls billing's ``usage_meter(session_factory)`` instead - the same
# ``UsageService`` - so the charge is billing's own conditional upsert in its
# own short transaction, finished with ``finalize_session`` (the billing rule:
# never a bare ``commit()`` outside a request).
#
# The session factory is the caller's when it passes one (images passes its
# pipeline's, which is the app's in the web process and the worker engine's in a
# worker). Otherwise a per-process ``NullPool`` engine is opened on the host's
# database URL, read the way ``worker_settings`` reads it (``BootstrapSettings``:
# ``SM_DATABASE_URL``, else the project ``.env``). ``NullPool`` because each task
# body runs on its own ``asyncio.run`` loop and a pooled asyncpg connection
# belongs to the loop that opened it.
#
# Without billing nothing is metered and every call is admitted. An installed
# billing that cannot meter (older than ``usage_meter``, or broken) raises:
# AI calls are never free because billing failed to load. A worker treats an *installed* billing as
# running: it cannot ask the web host's module list.

_lock = threading.Lock()
_engine: tuple[int, str, Any] | None = None  # (pid, url, DatabaseState)


def billing_installed() -> bool:
    """Whether ``sm_billing`` is installed at all: the only case left unmetered."""
    return _installed(constants.BILLING_PACKAGE)


def _billing_contract() -> Any:
    """Billing's metering contract; any import error propagates (fail closed)."""
    return importlib.import_module(constants.BILLING_USAGE_MODULE)


def _own_factory() -> Any:
    """This process's factory on the host database (rebuilt in a forked child)."""
    global _engine
    from simple_module_db import init_db
    from simple_module_hosting.bootstrap_settings import BootstrapSettings
    from sqlalchemy.pool import NullPool

    url = BootstrapSettings().database_url
    pid = os.getpid()
    with _lock:
        if _engine is not None and _engine[:2] == (pid, url):
            return _engine[2].session_factory
        state = init_db(url, poolclass=NullPool)
        _engine = (pid, url, state)
        return state.session_factory


async def dispose_worker_engine() -> None:
    """Forget the own engine (tests; a worker never needs to)."""
    global _engine
    with _lock:
        found, _engine = _engine, None
    if found is not None and found[0] == os.getpid():
        await found[2].engine.dispose()


async def consume_requests(
    tenant_id: str,
    qty: int = 1,
    *,
    idempotency_key: str,
    source: str,
    session_factory: Any = None,
) -> bool:
    """Charge ``qty`` AI requests to ``tenant_id``; ``False`` when the plan's
    limit refuses them (or the key was since refunded).

    ``idempotency_key`` makes a retry of the same call free: a replay answers
    the first call's outcome and counts nothing. Use job, image and attempt
    ids in it, never personal data. ``source`` names the caller (``images:classify``).
    """
    _check_qty(qty)
    if not idempotency_key or not source:
        raise ValueError("idempotency_key and source are required")
    if not billing_installed():
        return True
    usage_meter = getattr(_billing_contract(), "usage_meter", None)
    if usage_meter is None:  # installed, but cannot meter here: refuse, never run free
        raise RuntimeError(
            "the installed billing has no usage_meter (older than 0.0.14): "
            "AI requests outside a request cannot be metered"
        )
    meter = usage_meter(session_factory or _own_factory())
    outcome = await meter.consume(
        tenant_id, constants.METER_REQUESTS, qty, idempotency_key, source=source
    )
    return bool(outcome.ok)
