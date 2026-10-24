"""``RequiresQuota`` — count a request against a counter meter, or answer 402.

::

    @router.post("/chat", dependencies=[RequiresQuota("ai.requests")])
    async def chat(...): ...

The request's tenant is charged ``qty`` before the handler runs, in the
service's own short transaction. Refused → 402 ``quota_exceeded`` with
``meter``, ``limit``, ``used``, ``requested`` and ``resets_at``.

**Refunds only when the handler raises.** A handler that *returns* an error
response keeps the charge, the same rule ``get_db`` uses for rolling back. The
dependency is function-scoped, so it exits when the handler returns: a failure
delivering the response afterwards (the client disconnected) is not the
handler's and refunds nothing.

**One ``Idempotency-Key`` per operation; the handler runs at most once per
key.** A replay never reaches the handler — otherwise one unit of quota would
buy unlimited runs:

- the key's charge went through (the handler ran, or is running right now
  for a concurrent duplicate) → 409 ``idempotency_replay``, never a re-run.
  The first response is not stored (not in v1), so a client treats this as
  "already done";
- the key's first run raised and was refunded → 409
  ``idempotency_key_spent``: the key is spent (the metering rule) and a
  retry that should run again sends a new key;
- the same key on another route → 409 ``idempotency_conflict``.

Without the header every request is charged as its own operation.

With billing not started (``app.state.billing_usage`` missing) nothing is
limited and the dependency yields ``None``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import Depends, Request
from simple_module_db.tenancy import DEFAULT_TENANT_ID

from sm_billing import constants as c
from sm_billing.contracts.metering import Allowed, Exceeded, QuotaExceededError
from sm_billing.errors import BillingError
from sm_billing.lifecycle import is_multi_tenant
from sm_billing.metering.errors import IdempotencyReplay
from sm_billing.metering.validate import (
    ADJUST_PREFIX,
    KEY_MAX,
    QTY_MAX,
    REFUND_SUFFIX,
    SOURCE_MAX,
    check_text,
)

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"


def _tenant(request: Request) -> str:
    """The request's tenant; a single-tenant host meters everything as ``default``."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return tenant_id
    if not is_multi_tenant(request.app):
        return DEFAULT_TENANT_ID
    raise BillingError("tenant_required", 403)


def _key(request: Request, header: str) -> str:
    supplied = request.headers.get(header)
    if supplied is None:
        return f"req:{uuid4().hex}"
    key = supplied.strip()
    if not 0 < len(key) <= KEY_MAX or key.endswith(REFUND_SUFFIX) or key.startswith(ADJUST_PREFIX):
        raise BillingError("invalid_idempotency_key", 400)
    return key


def _source(request: Request) -> str:
    """The route's path template, so one key cannot be replayed on another route."""
    route = request.scope.get("route")
    return (getattr(route, "path", None) or request.url.path)[:SOURCE_MAX] or "/"


def RequiresQuota(  # noqa: N802 - reads like the framework's RequiresPermission
    meter: str, qty: int = 1, *, key_header: str = IDEMPOTENCY_HEADER
):
    """A dependency that charges ``qty`` of ``meter`` to the request's tenant."""
    check_text("meter", meter, 64)
    if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= QTY_MAX:
        raise ValueError(f"qty must be an integer from 1 to {QTY_MAX}")

    async def requires_quota(request: Request) -> AsyncIterator[Allowed | None]:
        usage = getattr(request.app.state, c.USAGE_STATE_ATTR, None)
        if usage is None:
            yield None
            return
        tenant_id = _tenant(request)
        key = _key(request, key_header)
        outcome = await usage.consume(tenant_id, meter, qty, key, source=_source(request))
        if isinstance(outcome, Exceeded):
            raise QuotaExceededError(meter, outcome)
        if not outcome.ok:
            raise BillingError("idempotency_key_spent", 409)
        if outcome.replayed:
            raise IdempotencyReplay()
        try:
            yield outcome
        except Exception:
            try:
                await usage.refund(tenant_id, meter, key)
            except Exception:
                # Never mask the handler's own error with the refund's.
                logger.exception("billing: refund failed tenant=%s meter=%s", tenant_id, meter)
            raise

    # ``scope="function"`` (FastAPI >= 0.121, hence billing's floor): the code
    # after ``yield`` runs when the handler returns, before the response is
    # sent. Request-scoped, an error while *sending* (a client that went away)
    # would be thrown in here too and refund work that was already done.
    return Depends(requires_quota, scope="function")
