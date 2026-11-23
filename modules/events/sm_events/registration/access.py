"""Who may *read* the registration target of an event (the form behind its builtin registration).

An editor who may edit an event but not read the record type it registers into sees an opaque
placeholder (no key, label or link), cannot change the form, and a save leaves it untouched: the
rule PR 6 gives a source's settings (``view_settings`` / ``restore_settings``). Unreadable is the
default: no viewer, no provider, an uninstalled provider are all "not readable".
"""

from __future__ import annotations

from typing import Any

from sm_events.calendar.plugins import registry
from sm_events.core import constants
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Event
from sm_events.registration import provider_call

__all__ = ["target_readable"]


async def target_readable(db: Any, event: Event, viewer: Any) -> bool:
    """Whether ``viewer`` may see ``event``'s registration target; ``True`` when it has none."""
    if (
        event.registration_mode != constants.REGISTRATION_MODE_BUILTIN
        or not event.registration_target
    ):
        return True
    provider = registry.registration_provider(event.registration_provider or "")
    if provider is None:
        return False
    return await provider_call.can_read(
        provider,
        db=db,
        tenant_id=bound_tenant(),
        target=event.registration_target,
        viewer=viewer,
    )
