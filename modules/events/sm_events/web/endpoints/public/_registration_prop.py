"""The public page's ``registration`` prop: where and which occurrence, never how full.

The page is cached and the same for everyone, so this holds no capacity, no count and no seat
state: the panel asks the registration provider's own route for those, live. ``none`` when there is
nothing to offer (no registration, a cancelled event or occurrence, a built-in provider this host
no longer has), so a stale setting shows no panel instead of a broken one.
"""

from __future__ import annotations

from datetime import UTC

from sm_events.calendar.plugins import registry
from sm_events.core import constants
from sm_events.core.web_urls import is_web_url
from sm_events.models import Event
from sm_events.web.endpoints.public._occurrence import ShownOccurrence
from sm_events.web.schemas.public_event import NextOccurrence, PublicRegistrationOut

__all__ = ["registration_prop"]


def _key(event: Event, shown: ShownOccurrence | None, series: bool) -> str | None:
    if not series:
        return str(event.id)
    if shown is None:
        return None
    original = shown.previous_start or shown.start  # a moved occurrence keeps its original key
    return f"{event.id}:{original.astimezone(UTC).strftime(constants.OCCURRENCE_KEY_STAMP)}"


def registration_prop(
    event: Event,
    *,
    shown: ShownOccurrence | None,
    series: bool,
    cancelled: bool,
    upcoming: list[NextOccurrence],
) -> PublicRegistrationOut:
    none = PublicRegistrationOut(
        mode=constants.REGISTRATION_MODE_NONE,
        url=None,
        provider=None,
        target=None,
        occurrence_key=None,
        upcoming=[],
    )
    if cancelled:
        return none
    if event.registration_mode == constants.REGISTRATION_MODE_EXTERNAL:
        url = event.registration_url if is_web_url(event.registration_url or "") else None
        return (
            none
            if url is None
            else none.model_copy(update={"mode": constants.REGISTRATION_MODE_EXTERNAL, "url": url})
        )
    if event.registration_mode != constants.REGISTRATION_MODE_BUILTIN:
        return none
    if (
        not event.registration_provider
        or not event.registration_target
        or registry.registration_provider(event.registration_provider) is None
    ):
        return none
    key = _key(event, shown, series)
    return PublicRegistrationOut(
        mode=constants.REGISTRATION_MODE_BUILTIN,
        url=None,
        provider=event.registration_provider,
        target=event.registration_target,
        occurrence_key=key,
        upcoming=[]
        if key is not None
        else [o for o in upcoming if o.status != "cancelled"][: constants.REGISTRATION_UPCOMING],
    )
