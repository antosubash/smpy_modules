"""Calling a registration provider: bounded, isolated, and never trusted.

Each call goes through :func:`~sm_events.calendar.plugins.plugin_isolation.run_isolated`, the
plugin runner's rule: a connection of its own (a rolled-back savepoint only where the engine
cannot give a second one), a wall-clock timeout of ``SOURCE_TIMEOUT_SECONDS`` and a refusal of any
write. So a provider call is **never in events' transaction**: it sees committed data and nothing
that must be atomic with an events write may depend on it.

What comes back is checked before it is used. A refusal that is the provider's own answer
(:class:`RegistrationTargetError`) is "unknown target" (422). A timeout, a write, a crash or an
answer of the wrong shape is "unavailable" (503); nothing the provider said is logged or shown
(an address could be in it), only the provider id and the exception class.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from sm_events.calendar.plugins.plugin_isolation import run_isolated
from sm_events.calendar.plugins.registration_types import (
    Registrant,
    RegistrationContext,
    RegistrationProvider,
    RegistrationTargetError,
    RegistrationTargetInfo,
)
from sm_events.core import constants
from sm_events.core.errors_registration import RegistrationUnavailable, UnknownRegistrationTarget

__all__ = ["can_read", "check_target", "recipients"]

logger = logging.getLogger(__name__)

_LABEL_MAX = 200
_URL_MAX = 2048
_EMAIL_MAX = 320
_NAME_MAX = 200
_LOCALE_MAX = constants.LOCALE_MAX


def _unavailable(provider: RegistrationProvider, what: str) -> RegistrationUnavailable:
    logger.error("events: registration provider %s: %s", provider.id, what)
    return RegistrationUnavailable(timed_out=True)


def _path_or_none(value: object) -> bool:
    """A site-relative path: it shows in the editor as a link, so it can never leave the site."""
    return value is None or (
        isinstance(value, str)
        and 0 < len(value) <= _URL_MAX
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and value.isprintable()
    )


def _valid_info(info: object) -> bool:
    return (
        isinstance(info, RegistrationTargetInfo)
        and isinstance(info.label, str)
        and 0 < len(info.label.strip()) <= _LABEL_MAX
        and _path_or_none(info.admin_url)
        and _path_or_none(info.attendees_url)
    )


async def check_target(
    provider: RegistrationProvider, *, db: Any, tenant_id: str, target: str, viewer: Any = None
) -> RegistrationTargetInfo:
    """What the provider says about ``target``; :class:`UnknownRegistrationTarget` when it is not
    one, :class:`RegistrationUnavailable` (503) when the provider could not answer."""
    try:
        info = await run_isolated(
            db,
            constants.SOURCE_TIMEOUT_SECONDS,
            lambda session: provider.check_target(
                RegistrationContext(tenant_id, session, viewer), target
            ),
        )
    except RegistrationTargetError:
        raise UnknownRegistrationTarget from None
    except Exception as exc:
        raise _unavailable(provider, f"check_target raised {type(exc).__name__}") from None
    if not _valid_info(info):
        raise _unavailable(provider, "check_target answered something malformed")
    return info


async def can_read(
    provider: RegistrationProvider, *, db: Any, tenant_id: str, target: str, viewer: Any
) -> bool:
    """Whether ``viewer`` may read ``target``. Fails **closed**: no viewer, no hook answer, a
    timeout or an error is "no" (the placeholder), never "yes"."""
    if viewer is None:
        return False
    if provider.can_read is None:
        return True  # the provider restricts nothing
    hook = provider.can_read
    try:
        answer = await run_isolated(
            db,
            constants.SOURCE_TIMEOUT_SECONDS,
            lambda session: hook(RegistrationContext(tenant_id, session, viewer), target),
        )
    except Exception as exc:
        logger.error(
            "events: registration provider %s: can_read raised %s", provider.id, type(exc).__name__
        )
        return False
    return answer is True


def _valid_registrant(value: object) -> bool:
    return (
        isinstance(value, Registrant)
        and isinstance(value.email, str)
        and 0 < len(value.email) <= _EMAIL_MAX
        and isinstance(value.name, str)
        and len(value.name) <= _NAME_MAX
        and isinstance(value.locale, str)
        and 0 < len(value.locale) <= _LOCALE_MAX
    )


async def recipients(
    provider: RegistrationProvider, *, db: Any, tenant_id: str, holders: Sequence[str]
) -> Mapping[str, Registrant]:
    """The confirmed registrants among ``holders`` (anyone else is absent), one batch. Only
    holders that were asked about, and only well-formed answers, survive."""
    if not holders:
        return {}
    wanted = set(holders)
    try:
        found = await run_isolated(
            db,
            constants.SOURCE_TIMEOUT_SECONDS,
            lambda session: provider.recipients(
                RegistrationContext(tenant_id, session), list(holders)
            ),
        )
    except Exception as exc:
        raise _unavailable(provider, f"recipients raised {type(exc).__name__}") from None
    if not isinstance(found, Mapping):
        raise _unavailable(provider, "recipients answered something malformed")
    return {
        holder: who for holder, who in found.items() if holder in wanted and _valid_registrant(who)
    }
