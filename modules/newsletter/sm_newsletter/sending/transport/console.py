"""The development transport: log the recipient and subject, keep the message.

Nothing leaves the server. Each message is kept in an in-process ring of the
last 50 per tenant (the bound tenant at send time), newest first through
:func:`captured`, and handed to every hook :func:`add_capture_hook`
registered. The log line holds only ``to`` and ``subject``, never the body.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.tenancy import bound_tenant
from sm_newsletter.sending.transport.base import DeliveryResult, TransportSession
from sm_newsletter.sending.transport.message import OutgoingMessage, build_mime

logger = logging.getLogger(__name__)

RING_SIZE = 50

CaptureHook = Callable[["CapturedMessage"], None]


@dataclass(frozen=True)
class CapturedMessage:
    tenant_id: str
    to: str
    subject: str
    html: str
    text: str
    headers: dict[str, str]
    at: datetime


_outbox: dict[str, deque[CapturedMessage]] = {}
_hooks: list[CaptureHook] = []


def captured(tenant_id: str) -> list[CapturedMessage]:
    """The tenant's captured messages, newest first."""
    return list(reversed(_outbox.get(tenant_id, ())))


def add_capture_hook(fn: CaptureHook) -> Callable[[], None]:
    """Call ``fn`` with every captured message; returns its (idempotent) remover."""
    _hooks.append(fn)

    def remove() -> None:
        if fn in _hooks:
            _hooks.remove(fn)

    return remove


class _ConsoleSession:
    async def send(self, msg: OutgoingMessage) -> DeliveryResult:
        try:
            mime = build_mime(msg)  # the same header checks as a real send
        except ValueError:
            # Answer like the SMTP session, so the caller closes its row.
            return DeliveryResult("rejected", None, "a header value is not valid")
        item = CapturedMessage(
            tenant_id=bound_tenant(),
            to=msg.to,
            subject=msg.subject,
            html=msg.html,
            text=msg.text,
            headers={name: str(value) for name, value in mime.items()},
            at=utcnow(),
        )
        _outbox.setdefault(item.tenant_id, deque(maxlen=RING_SIZE)).append(item)
        logger.info("Newsletter console transport: to=%s subject=%s", msg.to, msg.subject)
        for hook in list(_hooks):
            try:
                hook(item)
            except Exception:
                logger.warning("A console capture hook failed", exc_info=True)
        return DeliveryResult("accepted", 250, "captured by the console transport")


class ConsoleTransport:
    name = "console"
    supports_list_unsubscribe = True

    @asynccontextmanager
    async def session(self) -> AsyncIterator[TransportSession]:
        yield _ConsoleSession()
