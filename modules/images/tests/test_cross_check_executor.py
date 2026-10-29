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


def test_a_hook_that_returns_in_time_is_stored():
    async def main():
        return await cross_check.check(lambda g, r: {"ok": True}, _stand_in(), [], 1000)

    assert asyncio.run(main()) == {"ok": True}
