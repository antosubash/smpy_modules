"""The subject-key builders with no dependencies, so ``contracts`` can export them.

``sm_billing.subjects`` re-exports these; it imports the error and model
layers, which import ``contracts`` themselves.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sm_billing import constants as c

SubjectKind = Literal["tenant", "user"]


def subject_for_tenant(tenant_id: str) -> str:
    return tenant_id


def subject_for_user(user_id: str | uuid.UUID) -> str:
    """``user:<uuid>`` in canonical form, whatever spelling of the id is given.

    A hex or uppercase id gives the same key; a value that is no UUID raises
    ``ValueError`` rather than naming a subject no user can own.
    """
    return f"{c.USER_SUBJECT_PREFIX}{uuid.UUID(str(user_id))}"


def subject_mode(app: Any) -> SubjectKind:
    """The mode ``on_startup`` stored on ``app.state`` (tenant when unset).

    Web-process code only: it needs the app after billing's ``on_startup``. A
    Celery worker has no such app and would always read ``"tenant"`` here; it
    calls :func:`worker_subject_mode` instead.
    """
    return getattr(app.state, c.SUBJECTS_STATE_ATTR, c.SUBJECT_MODE_TENANT)


def worker_subject_mode() -> SubjectKind:
    """The ``subject_mode`` setting as stored, for code that has no app (a worker).

    Reads ``background_tasks.settings_for(BillingSettings, "sm_billing")``
    (DB-backed, cached about 30 s per process), so it needs the framework's
    ``simple_module_background_tasks`` installed and its sync engine
    configured, as every Celery worker has. Billing itself does not depend on
    it, hence the lazy import. The value is the stored one: after a change it
    may differ from the mode the web process booted with until that restarts.
    """
    from background_tasks import settings_for

    from sm_billing.settings import BillingSettings

    return settings_for(BillingSettings, c.PACKAGE).subject_mode
