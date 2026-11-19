"""Whether reminders can be delivered, and the first reason they cannot.

One function answers it for the control, the write routes and the Delivery card, so a user is
never promised mail that cannot arrive. The checks run in this order, and the first failure is
the reason (the codes are :data:`~sm_events.core.constants.AVAILABILITY_REASONS`):

1. ``disabled``: the ``reminders_enabled`` setting is off;
2. ``no_public_base_url``: the host's ``public_base_url`` is unset, so links would be relative;
3. ``no_mail_transport``: nothing (sender or resolver) is installed in this process;
4. ``console_mail``: the sender only logs (``delivers_email`` is false);
5. ``worker_access_unavailable``: a worker cannot work out who may still be reminded.

Whether a beat is running cannot be seen from here; with none, a follow is accepted and never
mailed. ``docs/operations.md`` says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simple_module_core.mail import mail_transport_installed, resolve_mail_sender

from sm_events.core import constants
from sm_events.reminders import worker_app
from sm_events.reminders.base_url import public_base_url

__all__ = ["Availability", "availability", "public_base_url"]

_DISABLED, _NO_URL, _NO_TRANSPORT, _CONSOLE, _NO_WORKER = constants.AVAILABILITY_REASONS


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str | None


def _refused(reason: str) -> Availability:
    return Availability(False, reason)


async def availability(app: Any, db: Any) -> Availability:
    if not getattr(app.state, constants.PACKAGE).settings.reminders_enabled:
        return _refused(_DISABLED)
    if not public_base_url(app):
        return _refused(_NO_URL)
    if not mail_transport_installed():
        return _refused(_NO_TRANSPORT)
    if not (await resolve_mail_sender(db)).delivers_email:
        return _refused(_CONSOLE)
    if not worker_app.worker_runtime_supported():
        return _refused(_NO_WORKER)
    return Availability(True, None)
