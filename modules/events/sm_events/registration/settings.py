"""Registration settings on an event: validation, the wall clock, and applying them.

**One writer.** ``registration_mode`` and ``registration_url`` belong together (``external`` needs a
URL, nothing else has one), so this module owns both: the create and update paths hand it the
``registration`` object and the legacy top-level ``registration_url`` and it settles them.

**What is validated here** (the body's own bounds are the schema's): the shape per mode, a window
that opens before it closes, a reminder lead from the allowed set, and, for ``builtin``, a provider
this host has and a target it accepts (one isolated provider call, see
:mod:`sm_events.registration.provider_call`).

**An uninstalled provider is kept, not erased.** Stored settings of a provider that is gone are left
as they are by every write that does not send registration settings; one that does is refused
(``registration_unavailable``), unless it sends them unchanged. The same rule as ``extra`` of an
uninstalled type.

**Nothing here commits, and the provider call is not in the transaction.** It runs on its own
connection, so a change to the settings is atomic with the event's write, while the provider's
answer is read from committed data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from sm_events.calendar.plugins import registry
from sm_events.calendar.plugins.registration_types import RegistrationTargetInfo
from sm_events.calendar.times import localize, parse_local, supported_instant
from sm_events.core import constants
from sm_events.core.constants.reminders_limits import REMINDER_LEADS
from sm_events.core.errors_registration import (
    InvalidRegistration,
    RegistrationUnavailable,
    UnknownRegistrationTarget,
)
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Event
from sm_events.registration import access, guards, provider_call
from sm_events.web.schemas.registration import RegistrationIn

__all__ = ["Applied", "apply_legacy_url", "apply_registration", "resolve"]

_FIELD = "registration"
_BUILTIN = constants.REGISTRATION_MODE_BUILTIN
_EXTERNAL = constants.REGISTRATION_MODE_EXTERNAL
_NONE = constants.REGISTRATION_MODE_NONE


class Applied(NamedTuple):
    changed: bool
    info: RegistrationTargetInfo | None
    """What the provider said about the target, when it was asked."""


def _bad(field: str) -> InvalidRegistration:
    return InvalidRegistration(field=f"{_FIELD}.{field}")


def _check_shape(reg: RegistrationIn) -> None:
    """Only ``builtin`` takes a provider, a target, a capacity, a window or a reminder; only
    ``external`` takes a URL."""
    if reg.mode == _EXTERNAL and reg.url is None:
        raise _bad("url")
    if reg.mode != _EXTERNAL and reg.url is not None:
        raise _bad("url")
    if reg.mode == _BUILTIN:
        if reg.target is None:
            raise _bad("target")
        return
    for name in ("provider", "target", "capacity", "opens_at_local", "closes_at_local"):
        if getattr(reg, name) is not None:
            raise _bad(name)
    if reg.show_seats:
        raise _bad("show_seats")
    if reg.reminder_minutes is not None:
        raise _bad("reminder_minutes")


def _instant(text: str | None, zone: ZoneInfo, field: str) -> datetime | None:
    if text is None:
        return None
    try:
        return supported_instant(localize(parse_local(text, zone, f"{_FIELD}.{field}"), zone))
    except ValueError:
        raise _bad(field) from None


def _window(reg: RegistrationIn, timezone: str) -> tuple[datetime | None, datetime | None]:
    zone = ZoneInfo(timezone)
    opens = _instant(reg.opens_at_local, zone, "opens_at_local")
    closes = _instant(reg.closes_at_local, zone, "closes_at_local")
    if opens is not None and closes is not None and opens >= closes:
        raise _bad("closes_at_local")
    return opens, closes


def _check_builtin(reg: RegistrationIn) -> None:
    """A ``builtin`` event names a provider this host has, and a reminder lead from the allowed
    set. With no provider installed at all there is nothing to name: unavailable."""
    if not registry.registration_providers():
        raise RegistrationUnavailable
    if reg.provider is None:
        raise _bad("provider")
    if registry.registration_provider(reg.provider) is None:
        raise RegistrationUnavailable
    if reg.reminder_minutes is not None and reg.reminder_minutes not in REMINDER_LEADS:
        raise _bad("reminder_minutes")


def _values(reg: RegistrationIn, window: tuple[datetime | None, datetime | None]) -> dict[str, Any]:
    builtin = reg.mode == _BUILTIN
    return {
        "registration_mode": reg.mode,
        "registration_url": reg.url,
        "registration_provider": reg.provider if builtin else None,
        "registration_target": reg.target if builtin else None,
        "registration_capacity": reg.capacity if builtin else None,
        "registration_opens_at": window[0],
        "registration_closes_at": window[1],
        "registration_show_seats": reg.show_seats if builtin else False,
        "registration_reminder_minutes": reg.reminder_minutes if builtin else None,
    }


def _form(values: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        values[k] for k in ("registration_mode", "registration_provider", "registration_target")
    )


async def _keep_unreadable_form(
    db: Any, event: Event, reg: RegistrationIn, viewer: Any
) -> RegistrationIn:
    """An event whose form this editor may not read keeps it: they can change the other settings,
    and a submitted form must be empty (the editor was shown none); anything else, **the stored one
    included**, is refused exactly as a form that does not exist (same code, message and cost).
    Accepting the stored one would tell a guesser that the guess is the hidden form's key."""
    if event.registration_mode != _BUILTIN or await access.target_readable(db, event, viewer):
        return reg
    allowed = [(_BUILTIN, None, None)]
    if registry.registration_provider(event.registration_provider or "") is None:
        # The provider is gone, not the editor's rights: nothing to guess at, and the settings sent
        # back unchanged are not a change (they could not be checked anyway).
        allowed.append((_BUILTIN, event.registration_provider, event.registration_target))
    if (reg.mode, reg.provider, reg.target) not in allowed:
        raise UnknownRegistrationTarget
    return reg.model_copy(
        update={
            "mode": _BUILTIN,
            "provider": event.registration_provider,
            "target": event.registration_target,
        }
    )


async def apply_registration(
    db: Any, event: Event, reg: RegistrationIn, *, creating: bool = False, viewer: Any = None
) -> Applied:
    """Validate ``reg`` and set it on ``event`` (its timezone is the wall clock's). Whether anything
    changed, and the provider's word on the target when it was asked. Call it after the event's
    own times are applied, so a zone change in the same write is the zone used. Settings equal to
    the stored ones are not a change, whatever the provider's state."""
    if not creating:
        reg = await _keep_unreadable_form(db, event, reg, viewer)
    _check_shape(reg)
    values = _values(reg, _window(reg, event.timezone))
    if all(getattr(event, name) == value for name, value in values.items()):
        return Applied(False, None)
    if reg.mode == _BUILTIN:
        _check_builtin(reg)
    if not creating:
        await guards.guard_seats(db, event, new=reg, orphaned_keys=())
    info = None
    if reg.mode == _BUILTIN and _form(values) != _form(
        {name: getattr(event, name) for name in values}
    ):
        provider = registry.registration_provider(reg.provider or "")
        assert provider is not None  # _check_builtin
        if viewer is None:  # no caller, no editor check to make: fail closed
            raise UnknownRegistrationTarget
        info = await provider_call.check_target(
            provider, db=db, tenant_id=bound_tenant(), target=reg.target or "", viewer=viewer
        )
    for name, value in values.items():
        setattr(event, name, value)
    return Applied(True, info)


def apply_legacy_url(event: Event, url: str | None) -> bool:
    """The old top-level ``registration_url``: a URL means ``external``, none means no registration
    unless it was a form of ours. A builtin event cannot be given one. Whether anything changed."""
    if url is not None and event.registration_mode == _BUILTIN:
        raise _bad("url")
    if url is None and event.registration_mode == _BUILTIN:
        return False
    mode = _EXTERNAL if url is not None else _NONE
    if (event.registration_url, event.registration_mode) == (url, mode):
        return False
    event.registration_url, event.registration_mode = url, mode
    return True


def resolve(
    registration: RegistrationIn | None, *, url: str | None, url_sent: bool
) -> RegistrationIn | None:
    """What to apply, from a body's two ways of saying it. The ``registration`` object wins and
    a top-level URL beside it must agree with it; with only a URL, ``None`` (the legacy path)."""
    if registration is None:
        return None
    if url_sent and url != registration.url:
        raise InvalidRegistration(field="registration_url")
    return registration
