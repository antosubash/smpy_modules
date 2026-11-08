"""SMTP through aiosmtplib, one connection per session.

``send`` speaks MAIL, RCPT and DATA itself instead of ``sendmail`` so the
outcome can say *where* a failure happened (see ``base``): a refusal is
``rejected`` and the envelope is cleared with ``RSET``; a drop or timeout
before the body went out is ``failed`` and the next send reconnects; a drop
or timeout after the body went out is ``unknown``. DATA is split for that
reason: the ``DATA`` command through aiosmtplib, then the body written and its
reply read on the client's protocol (dot-stuffed as aiosmtplib does).

That is a private seam: ``SMTP.protocol``, ``SMTPProtocol.write`` and
``SMTPProtocol.read_response`` are not documented API (checked against
aiosmtplib 3.0 to 5.1; ``tests/sending/test_smtp.py`` asserts they exist). A
session is sequential: the body read bypasses aiosmtplib's command lock, so
never call ``send`` concurrently on one session.

Time is bounded twice: ``timeout`` (20 s) per SMTP command, and
``send_deadline`` (45 s) around the whole of one ``send`` - a lazy reconnect,
MAIL, RCPT, DATA, the body and the final reply. The dispatcher's SQLite lease
is 120 s, so one recipient takes at most 45 s and leaves 75 s of margin.

Nothing here logs or returns the username, the password or the relay's AUTH
reply: :class:`TransportUnavailable` names the stage only.
"""

from __future__ import annotations

import asyncio
import re
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import aiosmtplib
from aiosmtplib import (
    SMTPDataError,
    SMTPException,
    SMTPResponseException,
    SMTPServerDisconnected,
    SMTPTimeoutError,
)

from sm_newsletter.core import crypto
from sm_newsletter.core.errors import TransportUnavailable
from sm_newsletter.sending.transport.base import DeliveryResult, Stage, TransportSession
from sm_newsletter.sending.transport.message import (
    OutgoingMessage,
    build_mime,
    envelope_address,
)

if TYPE_CHECKING:
    from sm_newsletter.core.settings import NewsletterSettings

_LINE_ENDINGS = re.compile(rb"(?:\r\n|\n|\r(?!\n))")
_LEADING_PERIOD = re.compile(rb"(?m)^\.")
# A dropped or stalled connection; anything else is a bug and propagates.
_LOST = (SMTPServerDisconnected, SMTPTimeoutError, ConnectionError, TimeoutError)


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    security: Literal["starttls", "tls"]
    username: str
    password: str = field(repr=False)
    timeout: float = 20  # per SMTP command
    send_deadline: float = 45  # one recipient in total, a lazy reconnect included


class SmtpTransport:
    name = "smtp"
    supports_list_unsubscribe = True

    def __init__(self, config: SmtpConfig, *, tls_context: ssl.SSLContext | None = None) -> None:
        self._config = config
        self._tls_context = tls_context

    @classmethod
    def from_settings(cls, settings: NewsletterSettings) -> SmtpTransport:
        return cls(
            SmtpConfig(
                host=settings.smtp_host,
                port=settings.smtp_port,
                security=settings.smtp_security,
                username=settings.smtp_username,
                password=crypto.decrypt_value(settings.smtp_password, "smtp_password"),
            )
        )

    def __repr__(self) -> str:
        c = self._config
        return f"SmtpTransport(host={c.host!r}, port={c.port}, security={c.security!r})"

    async def connect(self) -> aiosmtplib.SMTP:
        """A connected, secured and (with a username) logged-in client."""
        c = self._config
        client = aiosmtplib.SMTP(
            hostname=c.host,
            port=c.port,
            use_tls=c.security == "tls",
            start_tls=False,  # upgraded below, so a failure names its stage
            timeout=c.timeout,
            tls_context=self._tls_context,
        )
        try:
            await client.connect()
        except (SMTPException, OSError, UnicodeError) as exc:
            # aiosmtplib wraps an implicit-TLS handshake failure in SMTPConnectError.
            # UnicodeError: a host name IDNA cannot encode (e.g. a label over 63).
            tls = isinstance(exc, ssl.SSLError) or isinstance(exc.__cause__, ssl.SSLError)
            stage: Stage = "tls" if tls else "connect"
            raise TransportUnavailable(_stage(stage, exc), stage=stage) from exc
        try:
            if c.security == "starttls":
                await _upgrade(client)
            if c.username:
                await _login(client, c.username, c.password)
        except BaseException:
            client.close()
            raise
        return client

    @asynccontextmanager
    async def session(self) -> AsyncIterator[TransportSession]:
        smtp_session = _SmtpSession(self, await self.connect())
        try:
            yield smtp_session
        finally:
            await smtp_session.close()


async def _upgrade(client: aiosmtplib.SMTP) -> None:
    try:
        await client.starttls()
    except (SMTPException, ssl.SSLError, OSError) as exc:
        raise TransportUnavailable(_stage("tls", exc), stage="tls") from exc


async def _login(client: aiosmtplib.SMTP, username: str, password: str) -> None:
    try:
        await client.login(username, password)
    except SMTPResponseException as exc:
        # The reply text may echo the credential; keep the code only, and drop
        # the cause so no traceback carries it either.
        raise TransportUnavailable(f"SMTP auth failed ({exc.code})", stage="auth") from None
    except SMTPException as exc:
        raise TransportUnavailable(
            f"SMTP auth failed ({type(exc).__name__})", stage="auth"
        ) from None


def _stage(stage: str, exc: BaseException) -> str:
    return f"SMTP {stage} failed ({type(exc).__name__})"


class _SmtpSession:
    def __init__(self, transport: SmtpTransport, client: aiosmtplib.SMTP) -> None:
        self._transport = transport
        self._client: aiosmtplib.SMTP | None = client

    async def send(self, msg: OutgoingMessage) -> DeliveryResult:
        try:
            payload = build_mime(msg).as_bytes()
        except ValueError:
            # A bad header value (a subscriber address with a control
            # character): refused before any I/O; the value is never echoed.
            return DeliveryResult("rejected", None, "a header value is not valid")
        stage: list[Stage] = ["connect"]  # a cell, so the deadline handler can read it
        body_sent: list[bool] = [False]
        try:
            async with asyncio.timeout(self._transport._config.send_deadline):
                return await self._transact(msg, payload, stage, body_sent)
        except _LOST as exc:  # a lost connection in _transact, or the deadline's TimeoutError
            return self._lost(body_sent[0], f"connection lost ({type(exc).__name__})", stage[0])

    async def _transact(
        self, msg: OutgoingMessage, payload: bytes, stage: list[Stage], body_sent: list[bool]
    ) -> DeliveryResult:
        if self._client is None or not self._client.is_connected:
            try:
                self._client = await self._transport.connect()
            except TransportUnavailable as exc:
                self._client = None
                reconnect_stage: Stage | None = exc.stage  # type: ignore[assignment]
                return DeliveryResult("failed", None, exc.detail, reconnect_stage)
        client = self._client
        try:
            stage[0] = "mail"
            await client.mail(envelope_address(msg.sender))
            stage[0] = "rcpt"
            await client.rcpt(envelope_address(msg.to))
            stage[0] = "data"
            start = await client.execute_command(b"DATA")
            if start.code != 354:
                raise SMTPDataError(start.code, start.message)
            self._write_body(client, payload)
            body_sent[0] = True
            reply = await self._read_reply(client)
        except SMTPResponseException as exc:
            if exc.code < 0:
                # A malformed or oversized reply (aiosmtplib's -1): the stream is
                # desynced and the relay's answer unknown, so no RSET.
                return self._lost(body_sent[0], "malformed reply", stage[0])
            await self._reset()
            return DeliveryResult("rejected", exc.code, exc.message, stage[0])
        except UnicodeEncodeError:
            # aiosmtplib encodes MAIL/RCPT as ASCII; SMTPUTF8 is not negotiated.
            await self._reset()
            return DeliveryResult("rejected", None, "address is not ASCII (SMTPUTF8 unsupported)")
        return DeliveryResult("accepted", reply.code, reply.message, "data")

    def _lost(self, body_sent: bool, detail: str, stage: Stage) -> DeliveryResult:
        """Drop the connection; ``unknown`` once the body went out, else ``failed``."""
        self._drop()
        return DeliveryResult("unknown" if body_sent else "failed", None, detail, stage)

    def _write_body(self, client: aiosmtplib.SMTP, payload: bytes) -> None:
        protocol = client.protocol
        if protocol is None:
            raise SMTPServerDisconnected("Connection lost")
        data = _LEADING_PERIOD.sub(b"..", _LINE_ENDINGS.sub(b"\r\n", payload))
        if not data.endswith(b"\r\n"):
            data += b"\r\n"
        protocol.write(data + b".\r\n")

    async def _read_reply(self, client: aiosmtplib.SMTP) -> aiosmtplib.SMTPResponse:
        protocol = client.protocol
        if protocol is None:
            raise SMTPServerDisconnected("Connection lost")
        reply = await protocol.read_response(timeout=self._transport._config.timeout)
        if reply.code != 250:
            raise SMTPDataError(reply.code, reply.message)
        return reply

    async def _reset(self) -> None:
        """Clear the refused envelope; a relay that cannot is reconnected lazily."""
        if self._client is None or not self._client.is_connected:
            self._drop()
            return
        try:
            await self._client.rset()
        except (SMTPException, *_LOST):
            self._drop()

    def _drop(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is None or not client.is_connected:
            return
        with suppress(SMTPException, *_LOST, OSError):
            await client.quit()
        client.close()
