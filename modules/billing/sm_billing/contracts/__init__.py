"""Public contracts of the billing module.

The subject helpers are exported for worker-side callers (Celery tasks, jobs)
that meter outside a request: build the billing subject with these rather than
by hand, so a ``user:<uuid>`` key is always in its canonical form. A worker
reads the mode with ``worker_subject_mode()``; ``current_subject_mode(app)``
is for web-process code. Request code (entitlement checks included) takes the
subject from ``subject_for_request(request)``.

``RequiresQuota`` is the FastAPI dependency that charges a counter meter
before a route runs (ai's ``RequiresAiRequest`` is built on it, #336).
"""

from typing import Any

from sm_billing.core.subject_keys import subject_for_tenant, subject_for_user, worker_subject_mode
from sm_billing.core.subject_keys import subject_mode as current_subject_mode


def subject_for_request(request: Any) -> str:
    """The subject a request bills: :func:`sm_billing.core.subjects.for_request`.

    Pass it to ``entitlements.limit``/``has_feature`` (never
    ``request.state.tenant_id``, which in ``user`` mode is ``"default"`` for
    everyone). Imported lazily: ``subjects`` imports the error and model
    layers, which import this package.
    """
    from sm_billing.core.subjects import for_request

    return for_request(request)


async def subject_exists(db: Any, subject: str) -> bool:
    """Whether ``subject`` names something billable: :func:`sm_billing.core.subjects.exists`.

    ``"default"`` and an existing user's ``user:<uuid>`` are true; an unknown
    user or a non-canonical spelling is false. Imported lazily, as above.
    """
    from sm_billing.core.subjects import exists

    return await exists(db, subject)


def RequiresQuota(  # noqa: N802 - reads like the framework's RequiresPermission
    meter: str, qty: int = 1, *, key_header: str | None = None
) -> Any:
    """Charge ``qty`` of ``meter`` to the request's subject, or answer 402:
    :func:`sm_billing.metering.deps.RequiresQuota`.

    ``key_header`` is the idempotency header (default ``Idempotency-Key``).
    Imported lazily, as above: the dependency imports the session, subject and
    error layers.
    """
    from sm_billing.metering import deps

    if key_header is None:
        return deps.RequiresQuota(meter, qty)
    return deps.RequiresQuota(meter, qty, key_header=key_header)


__all__ = [
    "RequiresQuota",
    "current_subject_mode",
    "subject_exists",
    "subject_for_request",
    "subject_for_tenant",
    "subject_for_user",
    "worker_subject_mode",
]
