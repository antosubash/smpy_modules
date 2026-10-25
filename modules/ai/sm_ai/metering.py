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
"""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from fastapi import Depends, FastAPI

from sm_ai import constants

# The bound billing's validate.QTY_MAX enforces, repeated so an unmetered host
# rejects the same arguments a metered one does.
_QTY_MAX = 2**53


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
    try:
        return find_spec(constants.BILLING_QUOTA_MODULE) is not None
    except ModuleNotFoundError:  # no sm_billing, or one without metering
        return False


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
    if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= _QTY_MAX:
        raise ValueError(f"qty must be an integer from 1 to {_QTY_MAX}")
    if not billing_metering_installed():
        return Depends(_unmetered)
    from sm_billing.metering.deps import RequiresQuota

    return RequiresQuota(constants.METER_REQUESTS, qty)
