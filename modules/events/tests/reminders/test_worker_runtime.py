"""The headless worker runtime: built once, fails closed, never provisions a key."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from permissions.models import RolePermission
from sm_events.reminders import worker_app
from sm_events.reminders.availability import public_base_url

from tests.reminders.support import published, world
from tests.support.app import Directory, build_app
from tests.support.tokens import ROLES, USERS

SECRET = "never-logged-key-material"


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def host(monkeypatch):
    """The module's test app plays the host the worker would build."""
    app, state = await build_app()
    app.state.user_directory = Directory(dict(USERS), dict(ROLES))
    app.state.sm.settings.public_base_url = "https://events.example.org"
    clock, built = Clock(), []

    def create(settings):
        built.append(settings)
        return app

    monkeypatch.setattr(worker_app, "_settings", lambda: SimpleNamespace(marker="settings"))
    monkeypatch.setattr(worker_app, "_create_app", create)
    monkeypatch.setattr(worker_app, "_db_factory", lambda: state.session_factory)
    monkeypatch.setattr(worker_app, "_clock", clock)
    worker_app.reset_worker_app()
    async with state.session_factory() as db:
        yield SimpleNamespace(app=app, state=state, db=db, clock=clock, built=built)
    worker_app.reset_worker_app()
    await state.engine.dispose()


async def test_built_once_per_process(host):
    first = await worker_app.worker_runtime(host.db)
    second = await worker_app.worker_runtime(host.db)
    assert first is not None and second is not None
    assert len(host.built) == 1
    assert host.built[0].marker == "settings"


async def test_ttl_rebuild(host):
    await worker_app.worker_runtime(host.db)
    host.clock.now += worker_app.TTL_SECONDS - 1
    await worker_app.worker_runtime(host.db)
    assert len(host.built) == 1
    host.clock.now += 2
    await worker_app.worker_runtime(host.db)
    assert len(host.built) == 2  # a changed public base URL is picked up


async def test_reset_on_fork(host):
    await worker_app.worker_runtime(host.db)
    worker_app.reset_worker_app()
    await worker_app.worker_runtime(host.db)
    assert len(host.built) == 2


async def test_public_base_url_from_host(host):
    runtime = await worker_app.worker_runtime(host.db)
    assert runtime is not None
    assert runtime.public_base_url == "https://events.example.org"
    assert public_base_url(host.app) == runtime.public_base_url
    host.app.state.sm.settings.public_base_url = "https://new.example.org/"
    assert (await worker_app.worker_runtime(host.db)).public_base_url == "https://new.example.org"


async def test_the_runtime_answers_recipients(host):
    cals = await world(host.db)
    runtime = await worker_app.worker_runtime(host.db)
    got = await runtime.recipients(host.db, tenant_id="default", user_ids=["v", "ghost"])
    assert set(got) == {"v"} and got["v"].email == "v@example.com"
    assert cals


async def test_build_failure_fails_closed(host, monkeypatch, caplog):
    def boom(settings):
        raise RuntimeError(f"cannot build {SECRET}")

    monkeypatch.setattr(worker_app, "_create_app", boom)
    assert worker_app.worker_runtime_supported() is True  # nothing has failed yet
    with caplog.at_level(logging.DEBUG):
        assert await worker_app.worker_runtime(host.db) is None
        assert await worker_app.worker_runtime(host.db) is None
    assert worker_app.worker_runtime_supported() is False  # reported by ``availability``
    text = " ".join(f"{r.getMessage()} {r.args}" for r in caplog.records)
    assert "RuntimeError" in text and SECRET not in text
    assert len([r for r in caplog.records if "RuntimeError" in r.getMessage()]) == 1  # once
    # Not a crash loop: no rebuild inside the back-off, one attempt after it.
    attempts = []
    monkeypatch.setattr(worker_app, "_create_app", lambda s: attempts.append(1) or host.app)
    assert await worker_app.worker_runtime(host.db) is None and attempts == []
    host.clock.now += worker_app.RETRY_SECONDS + 1
    assert await worker_app.worker_runtime(host.db) is not None and attempts == [1]
    assert worker_app.worker_runtime_supported() is True


async def test_no_provisioned_key_builds_nothing(host, monkeypatch):
    """A worker never creates the deployment's session key as a side effect."""

    def refuse():
        raise worker_app.NoSecretKey

    monkeypatch.setattr(worker_app, "_settings", refuse)
    assert await worker_app.worker_runtime(host.db) is None
    assert host.built == []
    assert worker_app.worker_runtime_supported() is False


def test_settings_refuse_without_a_key(monkeypatch):
    monkeypatch.setattr(worker_app, "_has_key", lambda bootstrap: False)
    merged = []
    monkeypatch.setattr(worker_app, "_merge", lambda bootstrap: merged.append(bootstrap))
    with pytest.raises(worker_app.NoSecretKey):
        worker_app._settings()
    assert merged == []  # merge_host_settings would have written a key
    monkeypatch.setattr(worker_app, "_has_key", lambda bootstrap: True)
    worker_app._settings()
    assert len(merged) == 1


async def test_db_is_wired_when_the_app_has_none(host):
    host.app.state.sm.db = None
    await worker_app.worker_runtime(host.db)
    assert host.app.state.sm.db.session_factory is host.state.session_factory
    other = SimpleNamespace(session_factory="kept")
    worker_app.reset_worker_app()
    host.app.state.sm.db = other
    await worker_app.worker_runtime(host.db)
    assert host.app.state.sm.db is other  # an app that already has one keeps it


async def test_role_overlay_removal_denies(host):
    """A permission an admin gives a role on the permissions screen is honoured on the next
    tick, and withdrawing it denies on the next tick after that (the overlay is replayed)."""
    cals = await world(host.db)
    event = await published(host.db, cals["P"], title="Private")
    await host.db.commit()
    # ``v`` is a plain viewer with no share on the private calendar: no access to it.
    runtime = await worker_app.worker_runtime(host.db)
    wanted = {"v": {event.id}}
    from sm_events.reminders import recipients

    assert (
        await recipients.eligible(host.db, runtime, tenant_id="default", wanted=wanted)
    ).allowed == {}
    # The admin gives the ``viewer`` role events.manage (which sees every calendar).
    row = RolePermission(role_name="viewer", permission_key="events.manage")
    host.db.add(row)
    await host.db.commit()
    runtime = await worker_app.worker_runtime(host.db)
    got = await recipients.eligible(host.db, runtime, tenant_id="default", wanted=wanted)
    assert set(got.allowed) == {"v"}
    await host.db.delete(row)
    await host.db.commit()
    runtime = await worker_app.worker_runtime(host.db)
    got = await recipients.eligible(host.db, runtime, tenant_id="default", wanted=wanted)
    assert got.allowed == {}


async def test_an_overlay_that_cannot_be_read_denies(host, monkeypatch):
    async def broken(self):
        raise RuntimeError("database says no")

    monkeypatch.setattr("permissions.core.service.PermissionService.load_all_into_registry", broken)
    assert await worker_app.worker_runtime(host.db) is None


async def test_a_host_without_the_permissions_module_skips_the_overlay(host, monkeypatch):
    monkeypatch.setattr(worker_app, "_replay_overlay", None)
    assert await worker_app.worker_runtime(host.db) is not None
