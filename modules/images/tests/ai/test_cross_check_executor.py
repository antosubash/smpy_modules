"""A timed-out cross-check must not hold up the worker's loop shutdown.

Task bodies run under ``asyncio.run`` (``worker_runtime.run_task``), whose
shutdown waits for every default-executor thread. A hook still running past
:data:`CROSS_CHECK_TIMEOUT_S` is abandoned, so it must run elsewhere: the
group run ends at the timeout and the Celery task returns, not when (or if)
the plugin code finally does.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from sm_images.ai import cross_check


def _stand_in() -> SimpleNamespace:
    return SimpleNamespace(model_copy=lambda deep: None)


def test_a_hung_hook_does_not_delay_the_loops_shutdown(monkeypatch):
    monkeypatch.setattr(cross_check, "CROSS_CHECK_TIMEOUT_S", 0.1)
    release = threading.Event()
    entered = threading.Event()

    def hook(group, results):
        entered.set()
        release.wait(30)  # hung until the test lets it go
        return {}

    async def main() -> None:
        with pytest.raises(cross_check.CrossCheckTimedOut):
            await cross_check.check(hook, _stand_in(), [], 1000)

    started = time.monotonic()
    try:
        asyncio.run(main())
        elapsed = time.monotonic() - started
    finally:
        release.set()  # the abandoned thread returns; nothing waits for it
    assert entered.is_set()
    assert elapsed < 5, f"asyncio.run waited {elapsed:.1f} s for the abandoned hook"
    _wait_for_free_slots()  # the next test must start with every slot free


def _wait_for_free_slots(timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cross_check._SLOTS._value == cross_check.POOL_SIZE:  # type: ignore[attr-defined]
            return
        time.sleep(0.01)
    raise AssertionError("cross-check slots were not given back")


def test_a_hook_that_returns_in_time_is_stored():
    async def main():
        return await cross_check.check(lambda g, r: {"ok": True}, _stand_in(), [], 1000)

    assert asyncio.run(main()) == {"ok": True}


def test_admission_is_bounded_when_every_pool_thread_hangs(monkeypatch):
    """A 5th call fails at once as a timeout and never reaches the executor queue."""
    monkeypatch.setattr(cross_check, "CROSS_CHECK_TIMEOUT_S", 0.1)
    release = threading.Event()
    entered = threading.Semaphore(0)
    calls: list[int] = []

    def hung(group, results):
        entered.release()
        release.wait(30)
        return {}

    def fifth(group, results):
        calls.append(1)
        return {}

    async def run(fn):
        return await cross_check.check(fn, _stand_in(), [], 1000)

    async def main() -> None:
        for _ in range(cross_check.POOL_SIZE):
            with pytest.raises(cross_check.CrossCheckTimedOut):
                await run(hung)
        started = time.monotonic()
        with pytest.raises(cross_check.CrossCheckTimedOut):
            await run(fifth)
        assert time.monotonic() - started < 0.05
        assert cross_check._POOL._work_queue.qsize() == 0

    try:
        asyncio.run(main())
        assert calls == []
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:  # the slots free as the hooks return
            if cross_check._SLOTS.acquire(blocking=False):
                cross_check._SLOTS.release()
                break
            time.sleep(0.01)
        monkeypatch.setattr(cross_check, "CROSS_CHECK_TIMEOUT_S", 5.0)
        # a freed slot admits work again (may need every hung hook to finish)
        for _ in range(100):
            if cross_check._SLOTS._value == cross_check.POOL_SIZE:  # type: ignore[attr-defined]
                break
            time.sleep(0.01)
        assert asyncio.run(run(lambda g, r: {"ok": 1})) == {"ok": 1}
    finally:
        release.set()


def test_a_job_cancelled_while_queued_gives_its_slot_back(monkeypatch):
    """Its body never runs, so only a done-callback can free the slot."""
    monkeypatch.setattr(cross_check, "CROSS_CHECK_TIMEOUT_S", 0.1)
    release = threading.Event()
    busy = [cross_check._POOL.submit(release.wait, 30) for _ in range(cross_check.POOL_SIZE)]
    ran: list[int] = []
    try:

        async def main() -> None:
            with pytest.raises(cross_check.CrossCheckTimedOut):
                await cross_check.check(lambda g, r: ran.append(1) or {}, _stand_in(), [], 1000)

        asyncio.run(main())  # queued behind the busy threads, then cancelled
        assert ran == []
        # the cancel reaches the pool future on a later loop turn, so poll
        for _ in range(100):
            if cross_check._SLOTS._value == cross_check.POOL_SIZE:  # type: ignore[attr-defined]
                break
            time.sleep(0.05)
        assert cross_check._SLOTS._value == cross_check.POOL_SIZE  # type: ignore[attr-defined]
    finally:
        release.set()
        for job in busy:
            job.result(5)


def test_a_failed_submit_that_left_the_item_queued_frees_its_slot_when_it_runs(monkeypatch):
    """The item ``submit`` queued before failing releases its own slot once it runs."""
    real = cross_check._POOL.submit

    def queued_then_failed(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(cross_check._POOL, "submit", queued_then_failed)

    async def main() -> None:
        with pytest.raises(RuntimeError):
            await cross_check.check(lambda g, r: {}, _stand_in(), [], 1000)

    asyncio.run(main())
    deadline = time.monotonic() + 5
    while cross_check._SLOTS._value != cross_check.POOL_SIZE and time.monotonic() < deadline:  # type: ignore[attr-defined]
        time.sleep(0.01)
    assert cross_check._SLOTS._value == cross_check.POOL_SIZE  # type: ignore[attr-defined]
