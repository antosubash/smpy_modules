"""Request-scoped dependencies shared by the Records API and view endpoints.

Three kinds of thing live here, and all of them are about turning a raw
request into something a service function can take: the three static
permissions (design doc §10), the per-type ``allowed_roles`` narrowing that
sits on top of them, and the query-string grammar (``filter=``/``sort=``) so
the API and the record-list view parse it identically — the view has to
deep-link into exactly the state the API would show for the same query.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Query, Request
from simple_module_db import get_db
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants
from sm_records.index.query import Filter, FilterOp, Sort
from sm_records.models import RecordType
from sm_records.services.errors import Forbidden
from sm_records.services.types import get_type
from sm_records.settings import RecordsSettings

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


async def load_type(key: str, db: AsyncSession = Depends(get_db)) -> RecordType:
    """Resolve ``{key}`` from the URL. ``NotFound`` maps to 404 — see
    ``endpoints/api/_errors.py`` and the equivalent path in ``views.py``."""
    return await get_type(db, key)


def check_type_roles(request: Request, rtype: RecordType) -> None:
    """Design §10: a type's ``allowed_roles`` narrows the static ``records.edit``
    permission a caller already holds. Empty means any role holding the
    permission may write; this is invisible in the framework's role editor,
    which is the documented limitation, not a bug here.

    Applied on every *record* write, never on type management — narrowing is a
    property of a type's own records, not of the schema that defines it.
    """
    allowed = rtype.allowed_roles or []
    if not allowed:
        return
    user = getattr(request.state, "user", None)
    roles = set(getattr(user, "roles", None) or [])
    if not roles.intersection(allowed):
        raise Forbidden(
            f"type {rtype.key!r} is restricted to roles {sorted(allowed)}; "
            f"caller holds none of them"
        )


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


def _parse_filter(raw: str) -> Filter:
    """``field:op:value``, split on the first two colons — a value carrying
    its own colon (a URL, a timestamp) must not be truncated by it."""
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise HTTPException(
            status_code=400, detail=f"invalid filter {raw!r}: expected 'field:op:value'"
        )
    field, op_raw, value = parts
    try:
        op = FilterOp(op_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid filter {raw!r}: unknown operator {op_raw!r}"
        ) from exc
    parsed_value: Any
    if op is FilterOp.IN:
        parsed_value = value.split(",")
    elif op is FilterOp.IS_NULL:
        low = value.strip().lower()
        if low not in ("true", "false"):
            raise HTTPException(
                status_code=400,
                detail=f"invalid filter {raw!r}: is_null takes 'true' or 'false'",
            )
        parsed_value = low == "true"
    else:
        parsed_value = value
    return Filter(field=field, op=op, value=parsed_value)


def parse_filters(raw_filters: list[str] = Query(default=[], alias="filter")) -> list[Filter]:
    """``?filter=`` repeats; each is one term, ANDed together."""
    return [_parse_filter(item) for item in raw_filters]


def parse_sorts(raw_sorts: list[str] = Query(default=[], alias="sort")) -> list[Sort]:
    """``?sort=`` repeats; a leading ``-`` means descending."""
    return [
        Sort(field=item[1:], desc=True) if item.startswith("-") else Sort(field=item, desc=False)
        for item in raw_sorts
    ]


__all__ = [
    "actor",
    "check_type_roles",
    "get_settings",
    "load_type",
    "parse_filters",
    "parse_sorts",
    "require_edit",
    "require_manage_types",
    "require_view",
]
