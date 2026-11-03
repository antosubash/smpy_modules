"""Public contracts of the billing module.

The subject helpers are exported for worker-side callers (Celery tasks, jobs)
that meter outside a request: build the billing subject with these rather than
by hand, so a ``user:<uuid>`` key is always in its canonical form. A worker
reads the mode with ``worker_subject_mode()``; ``current_subject_mode(app)``
is for web-process code. Request code (entitlement checks included) takes the
subject from ``subject_for_request(request)``.
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


__all__ = [
    "current_subject_mode",
    "subject_exists",
    "subject_for_request",
    "subject_for_tenant",
    "subject_for_user",
    "worker_subject_mode",
]
