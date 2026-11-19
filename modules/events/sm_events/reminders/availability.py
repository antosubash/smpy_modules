"""Whether reminders can be delivered, and the first reason they cannot.

One function answers it for the control, the write routes and the Delivery card, so a user is
never promised mail that cannot arrive. The checks run in this order, and the first failure is
the reason (the codes are :data:`~sm_events.core.constants.AVAILABILITY_REASONS`):

1. ``disabled``: the ``reminders_enabled`` setting is off;
2. ``no_public_base_url``: the host's ``public_base_url`` is unset, so links would be relative;
3. ``no_mail_transport``: nothing (sender or resolver) is installed in this process;
4. ``console_mail``: the sender only logs (``delivers_email`` is false);

This runs in the web process, which cannot see two things: whether a beat is running (with
none, a follow is accepted and never mailed), and whether the worker's headless app can be built
(the beat finds out, sends nothing, and logs it). ``docs/operations.md`` says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simple_module_core.mail import mail_transport_installed, resolve_mail_sender

from sm_events.core import constants
from sm_events.core.host_settings import public_base_url

__all__ = ["Availability", "availability"]

_DISABLED, _NO_URL, _NO_TRANSPORT, _CONSOLE = constants.AVAILABILITY_REASONS


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
    return Availability(True, None)
