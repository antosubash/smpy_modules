"""Billing subjects: who a plan, a counter and a quota belong to.

A subject is the string every billing table keys on (the ``tenant_id``
columns). On a tenant-mode host it is the tenant id, or ``"default"`` on a
single-tenant host. In user mode it is ``"user:<uuid>"``, so a signed-in user
holds their own subscription and usage.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from simple_module_db.tenancy import DEFAULT_TENANT_ID
from sqlalchemy import select
from tenants.models import Tenant
from users.models import User

from sm_billing import constants as c
from sm_billing.errors import BillingError
from sm_billing.lifecycle import is_multi_tenant

SubjectKind = Literal["tenant", "user"]


def subject_for_tenant(tenant_id: str) -> str:
    return tenant_id


def subject_for_user(user_id: str | uuid.UUID) -> str:
    return f"{c.USER_SUBJECT_PREFIX}{user_id}"


def kind(subject: str) -> SubjectKind:
    return (
        c.SUBJECT_MODE_USER if subject.startswith(c.USER_SUBJECT_PREFIX) else c.SUBJECT_MODE_TENANT
    )


def user_id_of(subject: str) -> str | None:
    if kind(subject) != c.SUBJECT_MODE_USER:
        return None
    return subject[len(c.USER_SUBJECT_PREFIX) :]


def tenant_of(subject: str) -> str:
    """The tenant a subject lives under: a user subject has none, so ``"default"``."""
    return "default" if kind(subject) == c.SUBJECT_MODE_USER else subject


def subject_mode(app: Any) -> SubjectKind:
    """The mode ``on_startup`` stored on ``app.state`` (tenant when unset)."""
    return getattr(app.state, c.SUBJECTS_STATE_ATTR, c.SUBJECT_MODE_TENANT)


def for_request(request: Any) -> str:
    """The subject a request bills.

    Tenant mode: the request's tenant, else ``"default"`` on a single-tenant
    host, else 403 ``tenant_required``. User mode: the signed-in user, else
    401 ``subject_required`` — never ``"default"``, which would bill every
    anonymous caller to one shared counter.
    """
    if subject_mode(request.app) == c.SUBJECT_MODE_USER:
        user = getattr(request.state, "user", None)
        if user is None:
            raise BillingError("subject_required", 401)
        return subject_for_user(user.id)
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return subject_for_tenant(tenant_id)
    if not is_multi_tenant(request.app):
        return DEFAULT_TENANT_ID
    raise BillingError("tenant_required", 403)


def _as_uuid(raw: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw) if raw else None
    except ValueError:
        return None


async def exists(db: Any, subject: str) -> bool:
    if subject == "default":
        return True
    if kind(subject) == c.SUBJECT_MODE_USER:
        user_id = _as_uuid(user_id_of(subject))
        return user_id is not None and await db.get(User, user_id) is not None
    return await db.get(Tenant, subject) is not None


async def names(db: Any, subjects: list[str]) -> dict[str, tuple[str, str]]:
    """Subject -> (display name, slug). A user gives ``(email, "")``; an unknown one itself."""
    out: dict[str, tuple[str, str]] = {subject: (subject, "") for subject in subjects}
    users: dict[uuid.UUID, str] = {}
    tenant_ids: list[str] = []
    for subject in subjects:
        if kind(subject) == c.SUBJECT_MODE_USER:
            user_id = _as_uuid(user_id_of(subject))
            if user_id is not None:
                users[user_id] = subject
        elif subject != "default":
            tenant_ids.append(subject)
    # Two queries however long the list (the usage overview names every row).
    if users:
        stmt = select(User.id, User.email).where(User.id.in_(list(users)))
        for user_id, email in (await db.execute(stmt)).all():
            out[users[uuid.UUID(str(user_id))]] = (email, "")
    if tenant_ids:
        stmt = select(Tenant.id, Tenant.name, Tenant.slug).where(Tenant.id.in_(tenant_ids))
        for tenant_id, name, slug in (await db.execute(stmt)).all():
            out[tenant_id] = (name, slug)
    return out
