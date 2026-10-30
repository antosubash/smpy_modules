"""Close the socket when a TLS handshake is cancelled.

httpcore's backends close the raw stream when ``start_tls`` fails with an
``Exception``, but ``CancelledError`` is a ``BaseException``: a fetch cancelled
mid-handshake (our deadline, or the task being cancelled) leaves the TCP
connection open, and the connection object that would close it was never
assigned. :class:`CancelSafeBackend` wraps the pool's network backend so that
any ``BaseException`` during ``start_tls`` closes the raw stream, then re-raises.

httpx's ``AsyncHTTPTransport`` takes no network backend argument, so
:func:`harden` installs the wrapper on its connection pool (``_pool``, an
``httpcore.AsyncConnectionPool``, and its ``_network_backend``). If an httpx or
httpcore upgrade moves either, ``harden`` raises instead of silently running
without it.
"""

from __future__ import annotations

import ssl
import typing

import anyio
import httpcore
import httpx

__all__ = ["CancelSafeBackend", "harden"]


class _CancelSafeStream(httpcore.AsyncNetworkStream):
    def __init__(self, stream: httpcore.AsyncNetworkStream) -> None:
        self._stream = stream

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._stream.read(max_bytes, timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        await self._stream.write(buffer, timeout)

    async def aclose(self) -> None:
        await self._stream.aclose()

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            return await self._stream.start_tls(ssl_context, server_hostname, timeout)
        except BaseException:
            with anyio.CancelScope(shield=True):
                await self._stream.aclose()
            raise

    def get_extra_info(self, info: str) -> typing.Any:
        return self._stream.get_extra_info(info)


class CancelSafeBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, backend: httpcore.AsyncNetworkBackend) -> None:
        self._backend = backend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        stream = await self._backend.connect_tcp(host, port, timeout, local_address, socket_options)
        return _CancelSafeStream(stream)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        stream = await self._backend.connect_unix_socket(path, timeout, socket_options)
        return _CancelSafeStream(stream)

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def harden(transport: httpx.AsyncBaseTransport) -> httpx.AsyncBaseTransport:
    """Install :class:`CancelSafeBackend` on a real httpx transport's pool.

    Other transports (``httpx.MockTransport`` in tests) are returned unchanged.
    """
    if not isinstance(transport, httpx.AsyncHTTPTransport):
        return transport
    pool = getattr(transport, "_pool", None)
    backend = getattr(pool, "_network_backend", None)
    if not isinstance(pool, httpcore.AsyncConnectionPool) or backend is None:
        raise RuntimeError("httpx internals changed: cannot install CancelSafeBackend")
    if not isinstance(backend, CancelSafeBackend):
        pool._network_backend = CancelSafeBackend(backend)
    return transport
