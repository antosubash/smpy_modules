"""The retention sweep's loop (#101): it reads its settings every tick, so
switching it off on the Settings screen stops it without a restart, and it is
started once per module and stopped on shutdown."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sm_records.public_submissions import retention_loop
from sm_records.settings import RecordsSettings


def _app(settings: RecordsSettings) -> SimpleNamespace:
    services = SimpleNamespace(settings=settings)
    sm = SimpleNamespace(db=SimpleNamespace(session_factory=object()), event_bus="bus")
    return SimpleNamespace(state=SimpleNamespace(sm=sm, sm_records=services))


async def test_switched_off_the_loop_does_not_sweep(monkeypatch):
    calls: list[dict] = []
    ticks = 0

    async def fake_sweep(factory, settings, **kwargs):
        calls.append(kwargs)

    async def fake_sleep(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks > 1:
            raise RuntimeError("stop")

    monkeypatch.setattr(retention_loop, "sweep", fake_sweep)
    monkeypatch.setattr(retention_loop.asyncio, "sleep", fake_sleep)
    app = _app(RecordsSettings(public_submissions_retention_enabled=False))
    with pytest.raises(RuntimeError):
        await retention_loop._run(app, SimpleNamespace(settings=None))
    assert calls == []

    # A Settings-screen save replaces the object; the next tick reads it.
    app.state.sm_records.settings = RecordsSettings()
    ticks = 0
    with pytest.raises(RuntimeError):
        await retention_loop._run(app, SimpleNamespace(settings=None))
    assert calls == [{"bus": "bus"}]


async def test_a_failed_sweep_is_logged_and_the_loop_goes_on(monkeypatch):
    ticks = 0

    async def broken(*_args, **_kwargs):
        raise OSError("database went away")

    async def fake_sleep(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks > 2:
            raise RuntimeError("stop")

    monkeypatch.setattr(retention_loop, "sweep", broken)
    monkeypatch.setattr(retention_loop.asyncio, "sleep", fake_sleep)
    with pytest.raises(RuntimeError):
        await retention_loop._run(_app(RecordsSettings()), SimpleNamespace(settings=None))
    assert ticks == 3, "two sweeps failed, and the loop slept for a third"


async def test_started_once_and_stopped_on_shutdown(monkeypatch):
    started = asyncio.Event()

    async def forever(_app, _module):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(retention_loop, "_run", forever)
    module = SimpleNamespace()
    app = _app(RecordsSettings())
    retention_loop.start(module, app)
    task = getattr(module, retention_loop.TASK_ATTR)
    retention_loop.start(module, app)
    assert getattr(module, retention_loop.TASK_ATTR) is task, "no second loop on a second startup"
    await started.wait()
    await retention_loop.stop(module)
    assert task.cancelled() and getattr(module, retention_loop.TASK_ATTR) is None

    no_db = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=None)))
    retention_loop.start(module, no_db)
    assert getattr(module, retention_loop.TASK_ATTR) is None, "no database, nothing to sweep"


async def test_the_first_sweep_comes_soon_after_startup(monkeypatch):
    """A host restarted more often than the interval still sweeps."""
    slept: list[float] = []

    async def fake_sweep(*_args, **_kwargs):
        return None

    async def fake_sleep(seconds):
        slept.append(seconds)
        if len(slept) > 2:
            raise RuntimeError("stop")

    monkeypatch.setattr(retention_loop, "sweep", fake_sweep)
    monkeypatch.setattr(retention_loop.asyncio, "sleep", fake_sleep)
    settings = RecordsSettings(public_submissions_retention_interval_seconds=7200)
    with pytest.raises(RuntimeError):
        await retention_loop._run(_app(settings), SimpleNamespace(settings=None))
    assert slept == [retention_loop.FIRST_SWEEP_AFTER, 7200, 7200]
