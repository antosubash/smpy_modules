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

__all__ = ["MAX_WORKERS", "PatternPool", "PoolBusy", "close", "pool", "started"]

MAX_WORKERS: Final = 2

_WORKER = r"""
import json, re, sys
cache = {}
for line in sys.stdin:
    out = []
    for pattern, value in json.loads(line):
        rx = cache.get(pattern)
        if rx is None:
            if len(cache) > 256:
                cache.clear()
            rx = cache[pattern] = re.compile(pattern)
        out.append(rx.search(value) is not None)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
"""


class PoolBusy(RuntimeError):  # noqa: N818 - reads as the condition it is
    """No worker became free within the caller's wait."""


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
        line = await self.proc.stdout.readline()
        if not line:
            raise RuntimeError("records: the pattern worker exited")
        return [bool(item) for item in json.loads(line)]

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
            worker = self._idle.pop() if self._idle else await _Worker.start()
            try:
                result = await asyncio.wait_for(worker.run(checks), budget)
            except TimeoutError:
                await worker.kill()
                return None
            except BaseException:
                await worker.kill()
                raise
            self._idle.append(worker)
            return result
        finally:
            self._slots.release()

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
