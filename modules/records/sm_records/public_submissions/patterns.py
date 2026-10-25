"""Constraint patterns on a website visitor's input: matched off the event loop,
under one deadline per submission (#101).

A type's ``constraints.pattern`` is a Python ``re`` pattern, and keeps exactly
``re``'s meaning — no other engine (``regex``, RE2) agrees with it on ``\\w``,
on braces and on a dozen corners, and a constraint must not change what it
accepts because the sender is anonymous. ``re`` cannot be interrupted and
holds the GIL for a whole match, so neither a timeout argument nor a thread
bounds it: one admin's ``^(a+)+$`` and a visitor's ``aaaa…!`` would pin the
event loop for as long as the backtracking takes.

So every pattern check of one submission goes to a **worker process** in one
request, and the whole batch gets :data:`BUDGET_SECONDS`. A worker that does
not answer in time is killed — the only way to stop ``re`` — and the
submission is refused as invalid without validating anything further. The
write that follows runs inside ``patterns_prechecked()`` so the validator does
not match the same patterns again on the loop.

Workers are plain ``python -I -S -c`` children speaking JSON lines, started
on first use (a type with no pattern never starts one), at most
:data:`MAX_WORKERS` per process, and kept between requests.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Final

from sm_records.models import RecordType
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.services._payload import field_defs

__all__ = ["BUDGET_SECONDS", "MAX_WORKERS", "PatternPool", "check_patterns", "close"]

BUDGET_SECONDS: Final = 0.5
"""Wall-clock budget for every pattern match of one submission together."""

MAX_WORKERS: Final = 2
_WAIT_SECONDS: Final = 2.0
_STATE_ATTR: Final = "sm_records_pattern_pool"

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

    async def check(self, checks: list[tuple[str, str]], budget: float) -> list[bool] | None:
        """One result per check, or ``None`` when the batch ran out of time."""
        try:
            await asyncio.wait_for(self._slots.acquire(), _WAIT_SECONDS)
        except TimeoutError:
            raise SubmissionRefused(
                "rate_limited", "too many submissions; try again", headers={"Retry-After": "1"}
            ) from None
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


def _pool(app: Any) -> PatternPool:
    pool = getattr(app.state, _STATE_ATTR, None)
    if pool is None:
        pool = PatternPool()
        setattr(app.state, _STATE_ATTR, pool)
    return pool


async def close(app: Any) -> None:
    """Stop this app's workers (``on_shutdown``; tests)."""
    pool = getattr(app.state, _STATE_ATTR, None)
    if pool is not None:
        await pool.close()


async def check_patterns(app: Any, rtype: RecordType, data: dict[str, Any]) -> None:
    """Refuse ``data`` if a value misses its field's pattern, or if checking
    them all takes longer than the budget. A no-op without patterns."""
    patterns = {
        entry.key: entry.constraints["pattern"]
        for entry in field_defs(rtype)
        if (entry.constraints or {}).get("pattern")
    }
    keys = [key for key, value in data.items() if key in patterns and isinstance(value, str)]
    if not keys:
        return
    results = await _pool(app).check([(patterns[k], data[k]) for k in keys], BUDGET_SECONDS)
    if results is None:
        raise SubmissionRefused(
            "invalid",
            "this submission took too long to check",
            errors=[{"field": "__root__", "message": "took too long to check"}],
        )
    failed = [key for key, ok in zip(keys, results, strict=True) if not ok]
    if failed:
        raise SubmissionRefused(
            "invalid",
            f"{failed[0]!r} does not match its pattern",
            errors=[{"field": k, "message": f"must match {patterns[k]}"} for k in failed],
        )
