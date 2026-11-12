"""Who may read a newsletter list: :mod:`sm_records.contracts.newsletter`'s access
checks, split out by responsibility and re-exported there, the import path."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts._newsletter_args import _checked_tenant
from sm_records.core.tenancy import tenant_scope
from sm_records.public_submissions import campaign_reads
from sm_records.public_submissions.campaign_reads import SubscriberFilterError
from sm_records.records.services._access import CallerRoles, role_blocked


async def can_read_list(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    roles: Sequence[str] | CallerRoles | None,
) -> bool:
    """Whether a caller holding ``roles`` may read list ``type_key`` — records'
    own ``allowed_roles`` narrowing, widened by a ``records.type.<key>`` grant
    (pass :class:`CallerRoles` for that). ``roles=None`` is no caller (a
    worker, the CLI). ``False`` when the tenant has no such list."""
    tenant = _checked_tenant(tenant_id)
    with tenant_scope(tenant):
        try:
            rtype = await campaign_reads.list_type(session, tenant, type_key)
        except SubscriberFilterError:
            return False
        return rtype is not None and not role_blocked(rtype, roles)


def caller_roles(request: Any) -> CallerRoles:
    """The request's caller as :class:`CallerRoles`: their roles plus the
    ``records.type.<key>`` grants, with records' wildcard rule applied (an
    admin holds no per-type grants). Anonymous is ``CallerRoles([])``.

    What :func:`can_read_list` needs and another module cannot build itself.
    Reads the permission set the framework resolved for the request."""
    from sm_records.web.deps import caller_roles as _caller_roles

    return _caller_roles(request)
