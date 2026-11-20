"""A known secret for every subscription test: the stored-secret crypto reads it through the
provider, as a running app would install it."""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import ssl

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sm_events.core import crypto
from sm_events.feeds.subscriptions import client, policy

from tests.support.net import resolver  # noqa: F401 - fixture

SECRET = "subscription-test-secret"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(crypto, "_secret_provider", lambda: SECRET)
    monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS", raising=False)
    crypto._dotenv_previous.cache_clear()
    yield
    crypto._dotenv_previous.cache_clear()


# --- a real TLS server on loopback (the one real socket in the suite) ------------------------

ICS = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"


def _widen_loopback(monkeypatch) -> object:
    """The guard's address rule, widened to 127.0.0.1 for one test only; returns the real one."""
    loopback = ipaddress.ip_address("127.0.0.1")
    real = policy.address_allowed
    monkeypatch.setattr(
        policy,
        "address_allowed",
        lambda ip, *, allow_private: ip == loopback or real(ip, allow_private=allow_private),
    )
    return real


def _cert(subject: str, issuer_key, issuer_name, key, *, ca: bool, san: str | None):
    """A certificate that passes OpenSSL's strict X.509 checks (Python 3.13+ turns on
    ``VERIFY_X509_STRICT``: key identifiers and, for a CA, key usage are required)."""
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=ca,
                crl_sign=ca,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    )
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False
        )
    return builder.sign(issuer_key, hashes.SHA256())


@pytest.fixture
def tls_pki(tmp_path):
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test ca")])
    ca = _cert("test ca", ca_key, ca_name, ca_key, ca=True, san=None)
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = _cert("cal.example", ca_key, ca_name, leaf_key, ca=False, san="cal.example")
    cert_file, key_file = tmp_path / "leaf.pem", tmp_path / "leaf.key"
    cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server.load_cert_chain(cert_file, key_file)
    trust = ssl.create_default_context(cadata=ca.public_bytes(serialization.Encoding.PEM).decode())
    return server, trust


@pytest.fixture
async def tls_server(tls_pki, resolver, monkeypatch):  # noqa: F811
    server_ctx, client_ctx = tls_pki
    seen: dict = {"requests": []}

    def on_sni(_sock, name, _ctx):
        seen["sni"] = name

    server_ctx.sni_callback = on_sni

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen["connections"] = seen.get("connections", 0) + 1
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode().split("\r\n")
                seen["requests"].append(lines[0])
                for line in lines:
                    if line.lower().startswith("host:"):
                        seen["host"] = line.split(":", 1)[1].strip()
                payload = seen.get("body", ICS)  # a test may serve another feed
                kind = seen.get("type", b"text/calendar")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n\r\n%s"
                    % (kind, len(payload), payload)
                )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    port = server.sockets[0].getsockname()[1]
    resolver["cal.example"] = ["127.0.0.1"]
    resolver["wrong.example"] = ["127.0.0.1"]
    seen["real"] = _widen_loopback(monkeypatch)
    monkeypatch.setattr(
        client,
        "inner_transport",
        # the production transport's settings, trusting the test CA instead of the system's
        lambda: httpx.AsyncHTTPTransport(
            verify=client_ctx, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
        ),
    )
    try:
        yield port, seen
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
async def stalling_server(resolver, monkeypatch):  # noqa: F811
    """Accepts TCP on 127.0.0.1 and never answers the TLS ClientHello; records when the
    client's side of each connection is closed (EOF)."""
    events = {"accepted": asyncio.Event(), "eof": asyncio.Event()}
    writers: list[asyncio.StreamWriter] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        events["accepted"].set()
        while await reader.read(4096):
            pass
        events["eof"].set()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    resolver["stall.example"] = ["127.0.0.1"]
    _widen_loopback(monkeypatch)
    try:
        yield port, events
    finally:
        server.close()
        for writer in writers:
            writer.close()
        await asyncio.wait_for(server.wait_closed(), 2)
