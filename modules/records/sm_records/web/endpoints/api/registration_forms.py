"""``/api/records/registration-forms``: the registration types an event can point at (PR 9).

Called by the event editor's Registration section (records' own editor section, through events'
frontend slot): **list** the registration forms this caller may view (``records.view`` and the
type's ``allowed_roles``, like the type list; one the caller's role excludes is omitted, not
listed-then-refused), and **create** one with the defaults an event needs (``records.manage_types``,
the key ``event_registrations``, then ``_2``, ``_3``, and so on). The attendees are the type's own
record list, behind records' own grants: this route shows a key, a label and a link, never a person.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_core.permissions import WILDCARD
from simple_module_hosting.permissions import resolved_permissions_for
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from sm_records.contracts.public_submissions import KIND_REGISTRATION
from sm_records.core import constants
from sm_records.core.settings import RecordsSettings
from sm_records.public_submissions.registration.access import can_view
from sm_records.records.services import types as type_service
from sm_records.web.deps import (
    actor,
    caller_roles,
    get_settings,
    request_db,
    require_manage_types,
    require_view,
)
from sm_records.web.endpoints.api._errors import RecordsErrorRoute
from sm_records.web.endpoints.api._responses import TYPE_WRITE, responses
from sm_records.web.menu import mark_dirty

__all__ = ["router"]

BASE_KEY = "event_registrations"
LABEL = "Event registrations"
MAX_TRIES = 100

router = APIRouter(route_class=RecordsErrorRoute, responses=responses(*TYPE_WRITE))


class RegistrationFormRow(SQLModel):
    key: str
    label: str
    enabled: bool
    double_opt_in: bool
    """``False``: seats are taken at submit with no confirmation, so anyone can take seats without
    confirming an address (the event editor warns)."""
    attendees_url: str


class RegistrationFormList(SQLModel):
    items: list[RegistrationFormRow]
    can_create: bool
    """The create call would admit this caller (``records.manage_types``): the editor offers
    "Create a registration form" only then."""


class RegistrationFormCreated(SQLModel):
    key: str


def _defaults() -> dict[str, object]:
    """Consent is left for the organiser to word (required consent needs its text, so it cannot
    start required); the double opt-in is on and the form is on."""
    return {
        "kind": KIND_REGISTRATION,
        "enabled": True,
        "public_fields": [],
        "consent": {"required": False, "text": {}},
        "double_opt_in": True,
    }


@router.get("/registration-forms", response_model=RegistrationFormList, dependencies=[require_view])
async def list_registration_forms(
    request: Request, db: AsyncSession = Depends(request_db)
) -> RegistrationFormList:
    roles = caller_roles(request)
    held = resolved_permissions_for(request)
    rows = [
        RegistrationFormRow(
            key=rtype.key,
            label=rtype.label,
            enabled=bool((rtype.public_submissions or {}).get("enabled")),
            double_opt_in=bool((rtype.public_submissions or {}).get("double_opt_in", True)),
            attendees_url=f"{constants.VIEW_PREFIX}/{rtype.key}",
        )
        for rtype in sorted(await type_service.list_types(db), key=lambda t: t.key)
        if (rtype.public_submissions or {}).get("kind") == KIND_REGISTRATION
        and can_view(rtype, roles, {constants.PERM_VIEW})  # require_view already held
    ]
    return RegistrationFormList(
        items=rows, can_create=WILDCARD in held or constants.PERM_MANAGE_TYPES in held
    )


@router.post(
    "/registration-forms",
    response_model=RegistrationFormCreated,
    status_code=201,
    dependencies=[require_manage_types],
)
async def create_registration_form(
    request: Request,
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> RegistrationFormCreated:
    taken = {t.key for t in await type_service.list_types(db)}
    key = next(
        k for k in (BASE_KEY, *(f"{BASE_KEY}_{n}" for n in range(2, MAX_TRIES))) if k not in taken
    )
    await type_service.create_type(
        db,
        key=key,
        label=LABEL if key == BASE_KEY else f"{LABEL} {key.rsplit('_', 1)[1]}",
        settings=settings,
        fields_raw=[],
        public_submissions=_defaults(),
        actor=who,
    )
    mark_dirty(request.app)
    return RegistrationFormCreated(key=key)
