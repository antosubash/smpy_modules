"""Matching constraint patterns in a worker process, under a deadline.

A type's ``constraints.pattern`` is a Python ``re`` pattern and keeps exactly
``re``'s meaning — no other engine (``regex``, RE2) agrees with it on ``\\w``,
on braces and on a dozen corners. ``re`` cannot be interrupted and holds the
GIL for a whole match, so neither a timeout argument nor a thread bounds it:
an admin's ``^(a+)+$`` and anyone's ``aaaa…!`` would pin the event loop for as
long as the backtracking takes. A process can be killed, so every match on a
value somebody sent runs here: a batch of ``(pattern, value)`` pairs goes to a
pooled worker in one request, and a worker that does not answer within the
batch's budget is killed and the batch reported as over budget.

Workers are plain ``python -I -S -c`` children speaking JSON lines, started on
first use (a payload with no patterned value never starts one), at most
:data:`MAX_WORKERS` per event loop, and kept between requests.
:mod:`sm_records.services._patterns` decides what to check and what a verdict
means; this module only runs the batch.
"""

from __future__ import annotations

import asyncio
import json
import sys
import weakref
from typing import Final

__all__ = [
    "CHUNK",
    "MAX_WORKERS",
    "PatternPool",
    "PoolBusy",
    "WorkerFailed",
    "close",
    "pool",
    "started",
]

MAX_WORKERS: Final = 2

CHUNK: Final = 16384
"""Verdicts per response line. A batch may hold a verdict per value of a
20,000-row import, and asyncio's ``StreamReader`` refuses a line over its
64 KiB limit, so the answer comes back as lines of ``0``/``1`` characters
no longer than this, then a line holding only ``.``."""

_WORKER = r"""
import re, sys, json
CHUNK = @CHUNK@
cache = {}
for line in sys.stdin:
    out = []
    for pattern, value in json.loads(line):
        rx = cache.get(pattern)
        if rx is None:
            if len(cache) > 256:
                cache.clear()
            rx = cache[pattern] = re.compile(pattern)
        out.append("1" if rx.search(value) is not None else "0")
    for start in range(0, len(out), CHUNK):
        sys.stdout.write("".join(out[start:start + CHUNK]) + "\n")
    sys.stdout.write(".\n")
    sys.stdout.flush()
""".replace("@CHUNK@", str(CHUNK))


class PoolBusy(RuntimeError):  # noqa: N818 - reads as the condition it is
    """No worker became free within the caller's wait."""


class WorkerFailed(RuntimeError):  # noqa: N818 - reads as the condition it is
    """The worker died or answered something that is not a verdict list. The
    worker is gone; the caller refuses the write rather than guessing."""


class _Worker:
    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc

    @classmethod
    async def start(cls) -> _Worker:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-S",
            "-c",
            _WORKER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return cls(proc)

    async def run(self, checks: list[tuple[str, str]]) -> list[bool]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(checks).encode() + b"\n")
        await self.proc.stdin.drain()
        verdicts: list[bool] = []
        while True:
            line = (await self.proc.stdout.readline()).rstrip(b"\n")
            if line == b".":
                break
            if not line or len(line) > CHUNK or line.strip(b"01"):
                raise WorkerFailed("the pattern worker gave no well-formed answer")
            verdicts.extend(char == ord("1") for char in line)
        if len(verdicts) != len(checks):
            raise WorkerFailed(f"{len(verdicts)} verdicts for {len(checks)} checks")
        return verdicts

    async def kill(self) -> None:
        if self.proc.returncode is None:
            self.proc.kill()
        await self.proc.wait()


class PatternPool:
    def __init__(self, size: int = MAX_WORKERS) -> None:
        self._idle: list[_Worker] = []
        self._slots = asyncio.Semaphore(size)

    async def check(
        self, checks: list[tuple[str, str]], budget: float, *, wait: float | None = None
    ) -> list[bool] | None:
        """One verdict per pair, or ``None`` when the batch ran out of time.
        ``wait`` bounds the wait for a free worker (:class:`PoolBusy`)."""
        try:
            await asyncio.wait_for(self._slots.acquire(), wait)
        except TimeoutError:
            raise PoolBusy("every pattern worker is busy") from None
        try:
            worker = await self._take()
            try:
                result = await asyncio.wait_for(worker.run(checks), budget)
            except TimeoutError:
                await worker.kill()
                return None
            except (ValueError, OSError, WorkerFailed) as exc:
                # ``readline`` raises ValueError past its limit; a dead pipe is
                # an OSError. Either way the worker is unusable.
                await worker.kill()
                raise WorkerFailed(str(exc)) from exc
            except BaseException:
                await worker.kill()
                raise
            self._idle.append(worker)
            return result
        finally:
            self._slots.release()

    async def _take(self) -> _Worker:
        """An idle worker that is still alive, else a fresh one. One that died
        between requests (OOM-killed, signalled) would otherwise fail the next
        write for a reason that has nothing to do with it."""
        while self._idle:
            worker = self._idle.pop()
            if worker.proc.returncode is None:
                return worker
            await worker.kill()
        try:
            return await _Worker.start()
        except OSError as exc:
            raise WorkerFailed(str(exc)) from exc

    async def close(self) -> None:
        workers, self._idle = self._idle, []
        for worker in workers:
            await worker.kill()


_POOLS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, PatternPool] = (
    weakref.WeakKeyDictionary()
)


def pool() -> PatternPool:
    """This event loop's pool (one per loop: its pipes belong to it)."""
    loop = asyncio.get_running_loop()
    found = _POOLS.get(loop)
    if found is None:
        found = _POOLS[loop] = PatternPool()
    return found


def started() -> bool:
    """Whether this loop has started a pool (tests: the no-pattern fast path)."""
    return asyncio.get_running_loop() in _POOLS


async def close() -> None:
    """Stop this loop's workers (``on_shutdown``; tests)."""
    found = _POOLS.pop(asyncio.get_running_loop(), None)
    if found is not None:
        await found.close()
