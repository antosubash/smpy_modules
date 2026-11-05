"""A scripted in-memory transport for the delivery and dispatcher tests.

``script`` maps a recipient address to its answer, or to a list of answers
given one per send (the last one repeats). Anyone else is accepted.
``open_error`` makes :meth:`FakeTransport.session` raise it; ``on_send`` is
awaited with each message before the answer is returned (a test's probe of
what was committed before the SMTP call).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager

from sm_newsletter.core.errors import TransportUnavailable
from sm_newsletter.sending.transport import DeliveryResult, OutgoingMessage

ACCEPTED = DeliveryResult("accepted", 250, "2.0.0 Queued", "data")


class FakeTransport:
    name = "fake"
    supports_list_unsubscribe = True

    def __init__(
        self,
        script: Mapping[str, DeliveryResult | Sequence[DeliveryResult]] | None = None,
        *,
        open_error: TransportUnavailable | None = None,
        on_send: Callable[[OutgoingMessage], Awaitable[None]] | None = None,
    ) -> None:
        self._script = {
            to: [answer] if isinstance(answer, DeliveryResult) else list(answer)
            for to, answer in (script or {}).items()
        }
        self._open_error = open_error
        self._on_send = on_send
        self.sent: list[OutgoingMessage] = []
        self.opened = 0

    @asynccontextmanager
    async def session(self) -> AsyncIterator[FakeTransport]:
        if self._open_error is not None:
            raise self._open_error
        self.opened += 1
        yield self

    async def send(self, msg: OutgoingMessage) -> DeliveryResult:
        self.sent.append(msg)
        if self._on_send is not None:
            await self._on_send(msg)
        answers = self._script.get(msg.to)
        if not answers:
            return ACCEPTED
        return answers.pop(0) if len(answers) > 1 else answers[0]
