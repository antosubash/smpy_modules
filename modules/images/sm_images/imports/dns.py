"""Resolution for :mod:`sm_images.imports.fetch`, bounded in time and threads.

``getaddrinfo`` blocks, and cancelling the thread it runs on does not stop it.
So it runs on a small dedicated pool, and *admission* to that pool is bounded
too: a lookup takes a slot before it is submitted, and the slot is returned
only when its thread actually finishes (a done-callback), never on timeout. A
hung resolver therefore keeps counting against the bound; once every worker is
hung, further lookups wait for a slot only until their deadline and then fail
closed with :class:`FetchTimeoutError` - nothing queues behind the hung threads,
and the loop's default executor is never involved.

The slot count is a thread-safe counter rather than an ``asyncio.Semaphore``:
it is released from worker threads, and it outlives any one event loop (each
Celery task runs its own).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Final

import httpx

from sm_images.imports.errors import FetchTimeoutError
from sm_images.imports.url_safety import resolve_public

__all__ = ["DNS_TIMEOUT_SECONDS", "POOL_SIZE", "busy", "resolve_bounded"]

logger = logging.getLogger(__name__)

POOL_SIZE: Final = 8
DNS_TIMEOUT_SECONDS: float = 5.0
_ADMIT_POLL_SECONDS: Final = 0.01
_POOL: Final = ThreadPoolExecutor(max_workers=POOL_SIZE, thread_name_prefix="sm-images-dns")

_lock = threading.Lock()
_admitted = 0


def busy() -> int:
    """Slots held: lookups submitted whose thread has not finished yet."""
    return _admitted


def _try_admit() -> bool:
    global _admitted
    with _lock:
        if _admitted >= POOL_SIZE:
            return False
        _admitted += 1
        return True


def _release(_future: Future | None = None) -> None:
    global _admitted
    with _lock:
        _admitted -= 1


async def _admit() -> None:
    """Wait for a slot; the caller's timeout bounds the wait."""
    if _try_admit():
        return
    logger.warning(
        "DNS resolver pool saturated; waiting for a slot until the deadline",
        extra={"pool_size": POOL_SIZE},
    )
    while not _try_admit():
        await asyncio.sleep(_ADMIT_POLL_SECONDS)


async def _run[T](job: Callable[[], T]) -> T:
    await _admit()
    try:
        future = _POOL.submit(job)
    except BaseException:
        _release()
        raise
    future.add_done_callback(_release)  # also runs if the future is cancelled unstarted
    return await asyncio.wrap_future(future)


async def resolve_bounded(
    url: httpx.URL, allowed_ports: frozenset[int]
) -> tuple[str, tuple[str, ...]]:
    """``resolve_public`` on the DNS pool: admission and lookup together take at
    most ``DNS_TIMEOUT_SECONDS`` (and the caller's own deadline still applies)."""
    job = functools.partial(resolve_public, url, allowed_ports=allowed_ports)
    try:
        return await asyncio.wait_for(_run(job), DNS_TIMEOUT_SECONDS)
    except TimeoutError as error:
        raise FetchTimeoutError() from error
