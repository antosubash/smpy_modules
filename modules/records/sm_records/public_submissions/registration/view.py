"""``RegistrationView``: what one occurrence offers, and the form only while it is open (PR 9).

One uncached read, called by the (publicly cacheable) event page's panel. It answers **one 404** for
everything that is not a public, published event with this type as its registration form: an
unknown or non-registration type, a malformed or missing event or occurrence, a draft, a private
calendar, another tenant's event, an occurrence that does not exist. Nothing here says who is
registered, and the counts are the event's own (seats left only if it shows them).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions import KIND_REGISTRATION
from sm_records.contracts.public_submissions_api import (
    RegistrationAvailability,
    RegistrationEventInfo,
    RegistrationView,
)
from sm_records.core import locales
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import bound_tenant
from sm_records.models import RecordType
from sm_records.public_submissions.definition import page_locale, registration_definition
from sm_records.public_submissions.registration import seats
from sm_records.public_submissions.registration.tokens import canonical_event_id, canonical_key
from sm_records.public_submissions.tokens import host_secret
from sm_records.records.services.errors import NotFound
from sm_records.records.services.public import NOT_FOUND
from sm_records.records.services.types import get_type

__all__ = ["FEW_LEFT_DIVISOR", "registration_view"]

FEW_LEFT_DIVISOR = 5
"""\"Few left\": at most a fifth of the capacity (at least one seat). The one threshold."""


async def _type(db: AsyncSession, type_key: str) -> RecordType:
    try:
        rtype = await get_type(db, type_key)
    except NotFound:
        raise NotFound(NOT_FOUND) from None
    if (rtype.public_submissions or {}).get("kind") != KIND_REGISTRATION or not seats.available():
        raise NotFound(NOT_FOUND)
    return rtype


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


async def registration_view(
    app: Any,
    db: AsyncSession,
    type_key: str,
    event: str,
    occurrence: str,
    locale: str | None,
    settings: RecordsSettings,
) -> RegistrationView:
    rtype = await _type(db, type_key)
    try:
        event_id = canonical_event_id(event)
        key = canonical_key(event_id, occurrence)
    except ValueError:
        raise NotFound(NOT_FOUND) from None
    lang = page_locale(locale) or locales.default(settings)
    found = await seats.integration().describe(
        db,
        tenant_id=bound_tenant(),
        event_id=event_id,
        occurrence_key=key,
        target=rtype.key,
        locale=lang,
    )
    if found.state == "unavailable" or found.event is None:
        raise NotFound(NOT_FOUND)
    state = found.state
    enabled = bool((rtype.public_submissions or {}).get("enabled"))
    if state == "open" and not enabled:
        state = "closed"  # switched off: it says so, it does not pretend to be absent
    form = None
    if state == "open":
        form = registration_definition(
            rtype,
            settings,
            secret=host_secret(app),
            tenant=bound_tenant(),
            locale=lang,
            event_id=event_id,
            occurrence_key=key,
        )
    double = bool((rtype.public_submissions or {}).get("double_opt_in", True))
    few = (
        not double
        and found.capacity is not None
        and found.taken is not None
        and 0 < found.capacity - found.taken <= max(1, found.capacity // FEW_LEFT_DIVISOR)
    )
    return RegistrationView(
        availability=RegistrationAvailability(
            state=state,  # type: ignore[arg-type]
            seats_left=found.seats_left if double else None,
            few_left=few,
            opens_at=_iso(found.opens_at),
            closes_at=_iso(found.closes_at),
        ),
        event=RegistrationEventInfo(
            title=found.event.title,
            when_text=found.event.when_text,
            venue_name=found.event.venue_name,
            address=found.event.address,
        ),
        definition=form,
    )
