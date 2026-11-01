"""Public contracts of the billing module.

The subject helpers are exported for worker-side callers (Celery tasks, jobs)
that meter outside a request: build the billing subject with these rather than
by hand, so a ``user:<uuid>`` key is always in its canonical form.
"""

from sm_billing.subject_keys import subject_for_tenant, subject_for_user
from sm_billing.subject_keys import subject_mode as current_subject_mode

__all__ = ["current_subject_mode", "subject_for_tenant", "subject_for_user"]
