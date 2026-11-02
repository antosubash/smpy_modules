"""The subject-key builders and parsers with no heavy dependencies.

``contracts`` exports them, and ``lifecycle`` reads them, so they cannot live in
``sm_billing.subjects``: that imports the error and model layers, which import
``contracts`` and ``lifecycle`` themselves. ``subjects`` re-exports them.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from simple_module_db.tenancy import DEFAULT_TENANT_ID

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


def kind(subject: str) -> SubjectKind:
    return (
        c.SUBJECT_MODE_USER if subject.startswith(c.USER_SUBJECT_PREFIX) else c.SUBJECT_MODE_TENANT
    )


def user_uuid(subject: str) -> uuid.UUID | None:
    """The user a subject names — only in the canonical ``subject_for_user`` form.

    An uppercase or dashless spelling parses as the same UUID, but every
    request, list and checkout keys on the canonical string, so a row stored
    under another spelling would bill nobody. Such a subject names no user.
    """
    if kind(subject) != c.SUBJECT_MODE_USER:
        return None
    try:
        parsed = uuid.UUID(subject[len(c.USER_SUBJECT_PREFIX) :])
    except ValueError:
        return None
    return parsed if subject_for_user(parsed) == subject else None


def tenant_of(subject: str) -> str:
    """The tenant a subject lives under: a user subject has none, so ``"default"``."""
    return DEFAULT_TENANT_ID if kind(subject) == c.SUBJECT_MODE_USER else subject


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
