"""Pinning over a real socket and a real TLS handshake.

A TLS server on 127.0.0.1 holds a certificate for ``img.example`` only, signed
by a throwaway CA. DNS says ``img.example`` (and ``wrong.example``) is
127.0.0.1, and the guard's public-address check is widened to 127.0.0.1 inside
these tests alone. The fetch must dial the pinned IP, send SNI and Host for the
name, and verify the certificate against the name - so the wrong name fails.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import ssl

import httpx
import pytest
from sm_images.ingest.imports import fetch, url_safety
from sm_images.ingest.imports.fetch import safe_stream

x509 = pytest.importorskip("cryptography.x509")
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402


def _cert(subject: str, issuer_key, issuer_name, key, *, ca: bool, san: str | None):
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
    leaf = _cert("img.example", ca_key, ca_name, leaf_key, ca=False, san="img.example")
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
    client = ssl.create_default_context(cadata=ca.public_bytes(serialization.Encoding.PEM).decode())
    return server, client


@pytest.fixture
async def tls_server(tls_pki, resolver, monkeypatch):
    server_ctx, client_ctx = tls_pki
    seen: dict[str, str | None] = {}

    def on_sni(_sock, name, _ctx):
        seen["sni"] = name

    server_ctx.sni_callback = on_sni

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Keep-alive: answer requests on one connection until the client hangs up."""
        seen["connections"] = seen.get("connections", 0) + 1
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                for line in head.decode().split("\r\n"):
                    if line.lower().startswith("host:"):
                        seen["host"] = line.split(":", 1)[1].strip()
                body = b"pinned-ok"
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    port = server.sockets[0].getsockname()[1]
    resolver["img.example"] = ["127.0.0.1"]
    resolver["wrong.example"] = ["127.0.0.1"]
    loopback = ipaddress.ip_address("127.0.0.1")
    real_check = url_safety.is_public_address
    monkeypatch.setattr(
        url_safety, "is_public_address", lambda ip: ip == loopback or real_check(ip)
    )
    monkeypatch.setattr(
        fetch, "_inner_transport", lambda: httpx.AsyncHTTPTransport(verify=client_ctx)
    )
    try:
        yield port, seen
    finally:
        server.close()
        await server.wait_closed()


async def _get(url: str, port: int) -> bytes:
    stream = safe_stream(url, max_bytes=1000, timeout=5, allowed_ports=frozenset({port}))
    return b"".join([chunk async for chunk in stream])


async def test_pinned_tls_fetch_keeps_sni_host_and_verifies_the_name(tls_server):
    port, seen = tls_server
    assert await _get(f"https://img.example:{port}/a.jpg", port) == b"pinned-ok"
    assert seen["sni"] == "img.example"
    assert seen["host"] == f"img.example:{port}"


async def test_certificate_is_checked_against_the_hostname_not_the_ip(tls_server):
    port, _ = tls_server
    with pytest.raises(httpx.ConnectError, match=r"(?i)certificate|hostname"):
        await _get(f"https://wrong.example:{port}/a.jpg", port)


async def test_the_guard_is_not_widened_outside_the_override(tls_server):
    """Same server, but a port the caller did not allow: refused before dialling."""
    port, seen = tls_server
    with pytest.raises(url_safety.UnsafeURLError, match="port_not_allowed"):
        b"".join(
            [c async for c in safe_stream(f"https://img.example:{port}/", max_bytes=10, timeout=5)]
        )
    assert "sni" not in seen


async def test_a_reused_transport_verifies_each_name_on_a_shared_ip(tls_server):
    """A pooled connection verified for img.example is never reused for wrong.example."""
    port, seen = tls_server
    transport = fetch.PinnedTransport(allowed_ports=frozenset({port}))
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        for _ in range(2):
            assert (await client.get(f"https://img.example:{port}/a")).content == b"pinned-ok"
        assert seen["connections"] == 1  # keep-alive works within one name
        with pytest.raises(httpx.ConnectError, match=r"(?i)certificate|hostname"):
            await client.get(f"https://wrong.example:{port}/a")
