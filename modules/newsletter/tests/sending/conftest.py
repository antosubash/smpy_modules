"""An in-process aiosmtpd relay for the SMTP transport tests.

The server offers STARTTLS with a throwaway self-signed certificate (the
transport only speaks ``starttls`` or ``tls``) and AUTH with one fixed
credential. The recipient's local part scripts the answer:

- ``bounce@`` → ``550 5.1.1`` at RCPT;
- ``soft@`` → ``451`` after DATA;
- ``droprcpt@`` → the connection drops at RCPT (no reply);
- ``dropdata@`` → the connection drops after the body arrived (no reply);
- ``garble@`` → a non-numeric final reply after the body;
- ``stallrcpt@`` / ``stalldata@`` → no reply for ``STALL`` seconds at RCPT /
  after the body (pair with a shorter client timeout);
- anything else → accepted.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import socket
import ssl
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sm_newsletter.sending.transport.smtp import SmtpConfig, SmtpTransport

USERNAME = "relay-user"
STALL = 0.6
PASSWORD = "s3cret-Pa55word"


@dataclass
class Recorder:
    commands: list[str] = field(default_factory=list)
    delivered: list[Any] = field(default_factory=list)


class ScriptedHandler:
    def __init__(self, recorder: Recorder) -> None:
        self.rec = recorder

    async def handle_RSET(self, server, session, envelope):  # noqa: N802 - aiosmtpd's hook name
        self.rec.commands.append("RSET")
        return "250 OK"

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):  # noqa: N802 - aiosmtpd's hook name
        self.rec.commands.append(f"RCPT {address}")
        local = address.partition("@")[0]
        if local == "bounce":
            return "550 5.1.1 No such user"
        if local == "stallrcpt":
            await asyncio.sleep(STALL)
        if local == "droprcpt":
            server.transport.abort()
            return None
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - aiosmtpd's hook name
        local = envelope.rcpt_tos[0].partition("@")[0]
        if local == "soft":
            return "451 4.3.0 Try again later"
        if local == "garble":
            return "garbage reply"
        if local == "stalldata":
            await asyncio.sleep(STALL)
        if local == "dropdata":
            server.transport.abort()
            return None
        self.rec.delivered.append(envelope)
        return "250 2.0.0 Queued"


def _authenticate(server, session, envelope, mechanism, auth_data):
    ok = auth_data.login == USERNAME.encode() and auth_data.password == PASSWORD.encode()
    return AuthResult(success=ok, handled=False)  # handled=False: the server replies 535


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def tls_files(tmp_path_factory) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    folder = tmp_path_factory.mktemp("tls")
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture
def client_tls(tls_files) -> ssl.SSLContext:
    """A client context that trusts only the test certificate."""
    return ssl.create_default_context(cafile=str(tls_files[0]))


@pytest.fixture
def relay(tls_files):
    """Yield ``(port, recorder)`` for a running scripted relay."""
    server_tls = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_tls.load_cert_chain(str(tls_files[0]), str(tls_files[1]))
    recorder = Recorder()
    port = _free_port()
    controller = Controller(
        ScriptedHandler(recorder),
        hostname="127.0.0.1",
        port=port,
        tls_context=server_tls,
        authenticator=_authenticate,
        auth_require_tls=True,
    )
    controller.start()
    try:
        yield port, recorder
    finally:
        controller.stop()


@pytest.fixture
def make_transport(relay, client_tls):
    port, _ = relay

    def make(*, password: str = PASSWORD, timeout: float = 5.0, **overrides: Any) -> SmtpTransport:
        config = SmtpConfig(
            host="127.0.0.1",
            port=port,
            security="starttls",
            username=USERNAME,
            password=password,
            timeout=timeout,
        )
        return SmtpTransport(replace(config, **overrides), tls_context=client_tls)

    return make
