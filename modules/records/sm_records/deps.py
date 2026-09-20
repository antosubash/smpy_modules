"""Request-scoped dependencies shared by the Records API and view endpoints.

Three kinds of thing live here, and all of them are about turning a raw
request into something a service function can take: the three static
permissions (design doc §10), the per-type ``allowed_roles`` narrowing that
sits on top of them, and the request-scoped session.

The third kind — the query-string grammar (``filter=``/``sort=``/``expand=``)
— moved to :mod:`sm_records._grammar` for the 300-line cap and is re-exported
here, so an endpoint still imports one module. It is the API and the
record-list view parsing a query identically that lets the view deep-link
into exactly the state the API would show for the same query.
"""

from __future__ import annotations

from typing import Final

from fastapi import Depends, HTTPException, Query, Request
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants
from sm_records._grammar import (
    MALFORMED_FILTER,
    PageCursor,
    parse_cursor,
    parse_expand,
    parse_filters,
    parse_sorts,
    parse_view_filters,
)
from sm_records.models import RecordType
from sm_records.services._common import role_blocked
from sm_records.services.errors import Forbidden
from sm_records.services.types import get_type
from sm_records.settings import RecordsSettings

try:
    # The ``permissions`` module's checker additionally consults per-user
    # direct grants (``permissions_user_permission``, written by the
    # permissions admin screen) on top of roles — the framework's own
    # ``simple_module_hosting.permissions.RequiresPermission`` resolves roles
    # only, so a direct ``records.view`` grant with no role attached is
    # silently ignored by every route below. ``permissions`` is not a
    # ``simple_module_records`` dependency (a published module can't require
    # another plugin), so a host may install ``records`` without it — fall
    # back to the roles-only checker in that case rather than failing to import.
    from permissions.deps import RequiresPermission as _RequiresPermission
    from permissions.service import PermissionService as _PermissionService

    async def _check_permission(request: Request, db: AsyncSession, permission: str) -> None:
        service = _PermissionService(db, request.app.state.sm.permissions)
        await _RequiresPermission(permission)(request, service)

    RequiresPermission = _RequiresPermission
except ImportError:  # pragma: no cover - exercised only when `permissions` isn't installed
    from simple_module_hosting.permissions import RequiresPermission

    async def _check_permission(request: Request, db: AsyncSession, permission: str) -> None:
        RequiresPermission(permission)(request)


require_view = Depends(RequiresPermission(constants.PERM_VIEW))
require_edit = Depends(RequiresPermission(constants.PERM_EDIT))
require_manage_types = Depends(RequiresPermission(constants.PERM_MANAGE_TYPES))


def get_settings(request: Request) -> RecordsSettings:
    """The hydrated settings for this install.

    ``request.app.state.sm_records`` is the container
    :meth:`~sm_records.module.RecordsModule.register_settings` mounts; reading
    through it rather than a captured default is what makes a settings-screen
    edit take effect without a restart (``CLAUDE.md``: env → DB → default).
    """
    return request.app.state.sm_records.settings


REQUEST_SESSION_KEY: Final = "sm_records.request_session"
"""``request.scope`` key holding this request's session — see :func:`request_db`."""


async def request_db(request: Request, db: AsyncSession = Depends(get_db)) -> AsyncSession:
    """``get_db``, with the session findable from outside the dependency tree.

    ``RecordsErrorRoute`` turns a service exception into a JSON response
    *inside* the route handler, which means ``get_db`` never sees an exception
    and commits whatever the refused write already wrote. To roll that back it
    has to reach the session, and a route wrapper has no dependency tree to
    ask — so the session is parked on ``request.scope`` on the way in.

    Registering it here rather than taking it from the framework is a version
    thing: ``simple_module_db`` at the range this module depends on
    (``CLAUDE.md``: published modules pin ranges, never ``==``) exposes no
    request-scoped session accessor. ``get_db`` is still the dependency doing
    the work, and FastAPI caches it per request, so a route mixing
    ``Depends(get_db)`` and ``Depends(request_db)`` gets one session, not two.
    """
    request.scope[REQUEST_SESSION_KEY] = db
    return db


def request_session(request: Request) -> AsyncSession | None:
    """The session :func:`request_db` parked, or ``None`` outside a route that
    uses it."""
    return request.scope.get(REQUEST_SESSION_KEY)


async def load_type(key: str, db: AsyncSession = Depends(request_db)) -> RecordType:
    """Resolve ``{key}`` from the URL. ``NotFound`` maps to 404 — see
    ``endpoints/api/_errors.py`` and the equivalent path in ``views.py``."""
    return await get_type(db, key)


def check_type_roles(request: Request, rtype: RecordType) -> None:
    """Design §10: a type's ``allowed_roles`` narrows the static ``records.view``
    and ``records.edit`` permissions a caller already holds. Empty means any
    role holding the permission may read and write; this is invisible in the
    framework's role editor, which is the documented limitation, not a bug here.

    Applied on every *record* read (:func:`load_allowed_type`) and write, never
    on type management — narrowing is a property of a type's own records, and a
    ``records.manage_types`` holder has to stay able to open the schema screen
    and widen ``allowed_roles`` again.

    The predicate itself is ``services._common.role_blocked`` and is not
    re-implemented here: the read paths that report a relation *target* as
    ``restricted`` rather than refusing (``services.expand``, the referrers
    listing) answer the *same* question, admin wildcard included.
    """
    if role_blocked(rtype, caller_roles(request)):
        allowed = sorted(rtype.allowed_roles or [])
        raise Forbidden(
            f"type {rtype.key!r} is restricted to roles {allowed}; caller holds none of them"
        )


async def load_allowed_type(request: Request, rtype: RecordType = Depends(load_type)) -> RecordType:
    """:func:`load_type` plus the ``allowed_roles`` narrowing of design §10.

    The read-side twin of :func:`check_type_roles`, with deliberately the same
    refusal: redacting a read instead protects nothing when the caller can ask
    the narrowed type directly one request later. A dependency rather than a
    call per handler, so it replaces ``Depends(load_type)`` at the one place a
    read route resolves the type and cannot be forgotten.
    """
    check_type_roles(request, rtype)
    return rtype


def caller_roles(request: Request) -> list[str]:
    """The roles :func:`check_type_roles` narrows against, as a plain list.

    Handed to ``soft_delete_record`` so the same narrowing reaches the
    referrers a cascade or a set_null would touch — types the URL never
    names, and which ``check_type_roles`` therefore cannot see.
    """
    user = getattr(request.state, "user", None)
    return list(getattr(user, "roles", None) or [])


def actor(request: Request) -> str | None:
    """The value every ``created_by``/``updated_by`` in this module carries.

    ``UserContext.id`` — the same value ``auth.middleware`` hands to
    ``current_user_id.set(user_ctx.id)`` (``simple_module_db.listeners``),
    which is what stamps ``AuditMixin`` columns automatically. Passed
    explicitly here because ``RecordRevision`` and ``RecordTypeRevision`` are
    plain columns, not ``AuditMixin`` rows the listener would stamp on its
    own — the revision log needs the same identity by hand.
    """
    user = getattr(request.state, "user", None)
    return getattr(user, "id", None) if user is not None else None


async def parse_trashed(
    request: Request,
    trashed: bool = Query(default=False),
    db: AsyncSession = Depends(request_db),
) -> bool:
    """``?trashed=true`` lists the trash, and costs ``records.edit``.

    Enumerating soft-deleted records is how anything gets restored, so it is
    not a read for the ``records.view`` audience: a viewer sees what the type
    currently holds, an editor sees what it is holding *back*. Expressed as a
    dependency rather than a router-level one because it is conditional on
    the query parameter, which ``RequiresPermission`` cannot see.
    """
    if trashed:
        await _check_permission(request, db, constants.PERM_EDIT)
    return trashed


async def has_edit_permission(request: Request, db: AsyncSession) -> bool:
    """Whether the caller holds ``records.edit``, without raising.

    Used where a soft-deleted record's visibility depends on the caller's
    permission rather than always 403ing or always allowing — see
    ``endpoints/views.py::record_edit``.
    """
    try:
        await _check_permission(request, db, constants.PERM_EDIT)
    except HTTPException:
        return False
    return True


__all__ = [
    "MALFORMED_FILTER",
    "REQUEST_SESSION_KEY",
    "PageCursor",
    "actor",
    "caller_roles",
    "check_type_roles",
    "get_settings",
    "has_edit_permission",
    "load_allowed_type",
    "load_type",
    "parse_cursor",
    "parse_expand",
    "parse_filters",
    "parse_sorts",
    "parse_trashed",
    "parse_view_filters",
    "request_db",
    "request_session",
    "require_edit",
    "require_manage_types",
    "require_view",
]
