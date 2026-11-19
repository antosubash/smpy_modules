"""Whether reminders can be delivered, and why not, in the order the plan rules."""

from __future__ import annotations

import pytest
from simple_module_core.mail import (
    ConsoleMailSender,
    install_mail_resolver,
    install_mail_sender,
    reset_mail_sender,
)
from sm_events.core import constants
from sm_events.reminders import availability, worker_app
from sm_events.reminders.availability import Availability

from tests.support.app import build_app

ORIGIN = "https://events.example.org"


class _Sender:
    def __init__(self, delivers: bool) -> None:
        self.delivers_email = delivers

    async def send(self, message) -> None:  # pragma: no cover - never sent here
        raise AssertionError("availability never sends")


@pytest.fixture(autouse=True)
def _clean_mail():
    reset_mail_sender()
    yield
    reset_mail_sender()


@pytest.fixture
async def world(monkeypatch):
    """An app with everything satisfied; each test breaks one thing."""
    app, state = await build_app()
    app.state.sm.settings.public_base_url = ORIGIN
    install_mail_sender(_Sender(True))
    monkeypatch.setattr(worker_app, "worker_runtime_supported", lambda: True)
    async with state.session_factory() as db:
        yield app, db
    await state.engine.dispose()


async def test_everything_satisfied(world):
    app, db = world
    assert await availability.availability(app, db) == Availability(True, None)


def _break_setting(app):
    app.state.sm_events.settings.reminders_enabled = False


def _break_base_url(app):
    app.state.sm.settings.public_base_url = ""


def _break_transport(app):
    reset_mail_sender()


def _break_console(app):
    install_mail_sender(ConsoleMailSender())


def _break_worker(app):
    worker_app.worker_runtime_supported = lambda: False  # monkeypatched by ``world``


BREAKERS = [
    ("disabled", _break_setting),
    ("no_public_base_url", _break_base_url),
    ("no_mail_transport", _break_transport),
    ("console_mail", _break_console),
    ("worker_access_unavailable", _break_worker),
]


def test_reasons_are_the_constants_in_order():
    assert tuple(reason for reason, _ in BREAKERS) == constants.AVAILABILITY_REASONS


@pytest.mark.parametrize(("reason", "breaker"), BREAKERS)
async def test_each_reason(world, reason, breaker):
    app, db = world
    breaker(app)
    assert await availability.availability(app, db) == Availability(False, reason)


async def test_first_failing_check_wins(world):
    """Everything broken at once reports the first reason: ``disabled``."""
    app, db = world
    for _, breaker in BREAKERS:
        breaker(app)
    assert (await availability.availability(app, db)).reason == "disabled"
    app.state.sm_events.settings.reminders_enabled = True
    assert (await availability.availability(app, db)).reason == "no_public_base_url"


async def test_resolver_only_host(world):
    """A host with only a resolver (the outbox worker's shape) is available when it delivers."""
    app, db = world
    reset_mail_sender()

    async def resolver(_db):
        return _Sender(True)

    install_mail_resolver(resolver)
    assert await availability.availability(app, db) == Availability(True, None)

    async def console(_db):
        return ConsoleMailSender()

    install_mail_resolver(console)
    assert await availability.availability(app, db) == Availability(False, "console_mail")


async def test_public_base_url_is_trimmed(world):
    app, _ = world
    app.state.sm.settings.public_base_url = f"  {ORIGIN}/  "
    assert availability.public_base_url(app) == ORIGIN
    app.state.sm.settings.public_base_url = None
    assert availability.public_base_url(app) == ""
    app.state.sm.settings = object()
    assert availability.public_base_url(app) == ""


def test_the_headless_runtime_is_supported_until_it_fails():
    """Task 9: the stopgap exists, so a worker is supported until it has failed to build."""
    worker_app.reset_worker_app()
    assert worker_app.worker_runtime_supported() is True


async def test_public_base_url_follows_the_live_host_settings_not_the_boot_snapshot(world):
    """A ``host.*`` row saved on the Settings screen reloads ``app.state.host``; the boot
    snapshot (``app.state.sm.settings``) keeps what it had. Reminders read the live one."""
    from types import SimpleNamespace

    app, db = world
    app.state.sm.settings.public_base_url = ""
    assert (await availability.availability(app, db)).reason == "no_public_base_url"
    app.state.host = SimpleNamespace(settings=SimpleNamespace(public_base_url=f"{ORIGIN}/"))
    assert availability.public_base_url(app) == ORIGIN
    assert await availability.availability(app, db) == Availability(True, None)
    app.state.host = SimpleNamespace(settings=SimpleNamespace(public_base_url=""))
    assert (await availability.availability(app, db)).reason == "no_public_base_url"
