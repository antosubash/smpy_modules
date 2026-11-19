"""Fixtures the reminder send tests share."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_module_core.mail import install_mail_sender, reset_mail_sender
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar  # noqa: F401

from tests.reminders.support import published, world

START = datetime(2026, 7, 1, 10, tzinfo=UTC)


@pytest.fixture
async def cast(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            cals = await world(db)
            event = await published(db, cals["U"], title="Talk", starts_at=START)
            await db.commit()
    return db_state, event.id, event.revision


@pytest.fixture
def mailbox():
    """A delivering mail sender that keeps what it is given; removed afterwards."""
    from tests.reminders.tick_support import Mailbox

    reset_mail_sender()
    box = Mailbox()
    install_mail_sender(box)
    yield box
    reset_mail_sender()


@pytest.fixture
async def host():
    """An app whose directory knows ``v`` and ``u0..u39`` (viewers) and ``a`` (no roles)."""
    from sm_events.reminders.base_url import public_base_url  # noqa: F401

    from tests.reminders.support import ORIGIN
    from tests.support.app import Directory, build_app

    app, state = await build_app()
    users = {f"u{i}": (f"u{i}@example.com", f"U{i}", True) for i in range(40)}
    users.update({"v": ("v@example.com", "V", True), "a": ("a@example.com", "A", True)})
    roles = dict.fromkeys(users, ("viewer",))
    roles["a"] = ()
    app.state.user_directory = Directory(users, roles)
    app.state.sm.settings.public_base_url = ORIGIN
    yield app, state
    await state.engine.dispose()
