"""The transport seam: what a sender hands over and what it gets back.

A :class:`Transport` opens a :class:`TransportSession` (one relay connection,
many recipients); each :meth:`TransportSession.send` answers a
:class:`DeliveryResult` and never raises for a per-recipient failure. Outcomes:

- ``accepted`` - the relay answered 250 after the body;
- ``rejected`` - the relay refused it (MAIL, RCPT or DATA); ``code`` is its reply
  (``None`` when the message was refused before any I/O);
- ``failed``   - the connection dropped or timed out *before* the body was
  sent: nothing can have been delivered, so it is safe to retry;
- ``unknown``  - the connection dropped or timed out *after* the body was
  sent, before the final reply: it may or may not have been delivered.

``stage`` says where it happened (``data`` covers the ``DATA`` command and the
final reply); it is ``None`` for a refusal before any I/O.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from sm_newsletter.sending.transport.message import OutgoingMessage

Outcome = Literal["accepted", "rejected", "unknown", "failed"]

Stage = Literal["connect", "tls", "auth", "mail", "rcpt", "data"]

DETAIL_MAX = 500


@dataclass(frozen=True)
class DeliveryResult:
    outcome: Outcome
    code: int | None
    detail: str
    stage: Stage | None = None

    def __post_init__(self) -> None:
        if len(self.detail) > DETAIL_MAX:
            object.__setattr__(self, "detail", self.detail[:DETAIL_MAX])


class TransportSession(Protocol):
    async def send(self, msg: OutgoingMessage) -> DeliveryResult: ...


class Transport(Protocol):
    name: str
    supports_list_unsubscribe: bool

    def session(self) -> AbstractAsyncContextManager[TransportSession]:
        """Open a session; raises ``TransportUnavailable`` on connect/TLS/auth failure."""
        ...
