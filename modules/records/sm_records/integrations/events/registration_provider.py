"""``records:registration``: records' answer to events' questions about a registration target.

Registered from :mod:`sm_records.events_extensions`. Events asks two things, each on **a connection
of its own, read-only** (the plugin runner's rule): does this target (a registration type's key)
exist, and who are these holders right now. The holder is a record's uuid; the answer for a holder
is its registrant **only while the registration is confirmed** (``registered``, untrashed): a
pending, cancelled or trashed one is simply absent, so no reminder goes to someone who did not
confirm or who cancelled.

Nothing personal is logged, and events stores nothing of what comes back (an address is read at
send time and forgotten).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sm_events.contracts.extensions import (
    Registrant,
    RegistrationContext,
    RegistrationProvider,
    RegistrationTargetError,
    RegistrationTargetInfo,
)
from sqlalchemy import select

from sm_records.contracts.public_submissions import KIND_REGISTRATION
from sm_records.core import constants
from sm_records.core.tenancy import bound_tenant, tenant_scope
from sm_records.models import tables_for
from sm_records.records.services.errors import NotFound
from sm_records.records.services.types import get_type, list_types

__all__ = ["LABEL_KEY", "PROVIDER_ID", "provider"]

PROVIDER_ID = "records:registration"
LABEL_KEY = "records.events.registration.label"
_DEFAULT_LOCALE = "en"


def _bound(ctx: RegistrationContext) -> None:
    """The context names the tenant the call is for; it must be the one bound, never another."""
    if ctx.tenant_id != bound_tenant():
        raise RegistrationTargetError("not this tenant's")


async def _check_target(ctx: RegistrationContext, target: str) -> RegistrationTargetInfo:
    _bound(ctx)
    with tenant_scope(ctx.tenant_id):
        try:
            rtype = await get_type(ctx.db, target)
        except NotFound:
            raise RegistrationTargetError("no such registration form") from None
        if (rtype.public_submissions or {}).get("kind") != KIND_REGISTRATION:
            raise RegistrationTargetError("not a registration form")
        # Whoever sees the attendees needs records' own grants on this type; pointing an event at
        # the form exposes no attendee, so this checks existence and kind, not the editor's rights.
        base = f"{constants.VIEW_PREFIX}/{rtype.key}"
        return RegistrationTargetInfo(label=rtype.label, admin_url=base, attendees_url=base)


async def _recipients(ctx: RegistrationContext, holders: Sequence[str]) -> Mapping[str, Registrant]:
    _bound(ctx)
    wanted: dict[str, str] = {}
    for holder in holders:
        try:
            wanted[uuid.UUID(holder).hex] = holder
        except ValueError:
            continue
    found: dict[str, Registrant] = {}
    if not wanted:
        return found
    with tenant_scope(ctx.tenant_id):
        tenant = bound_tenant()
        for rtype in await list_types(ctx.db):
            if (rtype.public_submissions or {}).get("kind") != KIND_REGISTRATION:
                continue
            cls = tables_for(rtype).record
            stmt = select(cls).where(
                cls.uuid.in_(list(wanted)), cls.tenant_id == tenant, cls.type_id == rtype.id
            )
            for record in (await ctx.db.execute(stmt)).scalars():
                data: dict[str, Any] = record.data or {}
                if data.get("sm_status") == "registered" and data.get("sm_email"):
                    found[wanted[record.uuid]] = Registrant(
                        email=str(data["sm_email"]),
                        name=str(data.get("sm_name") or ""),
                        locale=str(data.get("sm_locale") or _DEFAULT_LOCALE),
                    )
    return found


def provider() -> RegistrationProvider:
    return RegistrationProvider(
        id=PROVIDER_ID, label_key=LABEL_KEY, check_target=_check_target, recipients=_recipients
    )
