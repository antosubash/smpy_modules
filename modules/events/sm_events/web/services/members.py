"""Who counts as a member of the tenant a request runs in.

The share picker offers only these, and an ownership transfer accepts only
these: neither may reveal or hand a calendar to an account of another
organisation. On a single-tenant host there is no membership to filter by.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from fastapi import Request
from simple_module_core.tenancy import tenant_member_ids
from simple_module_core.user_directory import DirectoryUser, NullUserDirectory, get_user_directory

from sm_events.core import constants
from sm_events.core.errors import ServiceUnavailable
from sm_events.core.tenancy import DEFAULT_TENANT, TenancyMode, bound_tenant, mode_of, request_mode

__all__ = ["active_member", "directory_or_unavailable", "members_only", "unscoped_single"]


def unscoped_single(request: Request) -> bool:
    """True only for a single-tenant host where nothing upstream resolved
    another tenant. Anything else (multi, a mis-detected mount, an upstream
    tenant, a bound tenant other than the default) filters by membership."""
    if request_mode(request, mode_of(request.app)) is not TenancyMode.SINGLE:
        return False
    upstream = getattr(request.state, "tenant_id", None)
    return upstream in (None, DEFAULT_TENANT) and bound_tenant() == DEFAULT_TENANT


def directory_or_unavailable(request: Request) -> Any:
    """The app's user directory; a 503 when there is none to ask."""
    directory = get_user_directory(request.app)
    if isinstance(directory, NullUserDirectory):
        raise ServiceUnavailable(
            constants.DIRECTORY_UNAVAILABLE_DETAIL, code=constants.DIRECTORY_UNAVAILABLE_CODE
        )
    return directory


async def members_only(
    request: Request, db: Any, users: Collection[DirectoryUser]
) -> list[DirectoryUser]:
    """*users* narrowed to the bound tenant's members (all of them on an
    unscoped single-tenant host). Fail closed: no membership store, nobody."""
    if unscoped_single(request):
        return list(users)
    members = await tenant_member_ids(request.app, db, bound_tenant(), [u.id for u in users])
    return [u for u in users if u.id in (members or set())]


async def active_member(request: Request, db: Any, user_id: str) -> bool:
    """Is ``user_id`` an active account in the bound tenant?"""
    directory = directory_or_unavailable(request)
    known = (await directory.get_many(db, [user_id])).get(user_id)
    if known is None or not known.is_active:
        return False
    return bool(await members_only(request, db, [known]))
