"""``newsletter.dispatch`` through the worker runtime, with no app (S11, S12, A5, A7).

Synchronous tests on purpose, like ``test_worker.py``: the task body starts its
own event loop. The worker reaches the database only through ``sync_db``'s URL
and finds its settings and secret there, as a real worker does.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from background_tasks.core import sync_db
from simple_module_db.stored_settings import Setting
from sm_newsletter import tasks
from sm_newsletter.core import tokens, worker
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.constants import UNSUBSCRIBE_PREFIX
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import SendAttempt
from sm_newsletter.sending.transport import console
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.campaign_world import campaign_row, seed_campaign, seed_render, send_rows
from tests.support.freeze_world import subscribers
from tests.support.records_seed import seed_list
from tests.support.sending import T
from tests.support.worker_env import encrypted, isolate_worker_env, reset_worker_caches

pytestmark = pytest.mark.skipif(
    USING_POSTGRES, reason="the worker test points sync_db at its own SQLite file"
)

SECRET = "stored-host-secret"
ENDPOINT = "PUT /api/newsletter/settings/smtp-password"
LOGGERS = ("sm_newsletter", "aiosmtplib", "celery")


@dataclass
class World:
    db_file: Path
    cid: int
    engine: Any

    def put(self, key: str, value: str, value_type: str = "string") -> None:
        with Session(self.engine) as s:
            s.execute(delete(Setting).where(Setting.key == key))
            s.add(Setting(key=key, value=value, value_type=value_type))
            s.commit()

    def smtp_to(self, port: int, password: str) -> None:
        self.put("sm_newsletter.transport", "smtp")
        self.put("sm_newsletter.smtp_host", "127.0.0.1")
        self.put("sm_newsletter.smtp_port", str(port), "int")
        self.put("sm_newsletter.smtp_password", password)


async def _seed(db_file: Path) -> int:
    """The list ``news`` with two confirmed subscribers and a ``scheduled``
    campaign due a minute ago (by the real clock: the task uses it)."""
    state = await make_db_state(file=db_file)
    await seed_list(state, T)
    await subscribers(state, 2)
    cid = await seed_campaign(
        state, T, status="scheduled", scheduled_at=utcnow() - timedelta(minutes=1)
    )
    await seed_render(state, T, cid)
    await state.engine.dispose()
    return cid


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A console sender configured in the settings table; no secret anywhere
    until a test stores ``host.secret_key``."""
    isolate_worker_env(monkeypatch, tmp_path)
    monkeypatch.setattr(console, "_outbox", {})
    db_file = tmp_path / "worker.db"
    cid = asyncio.run(_seed(db_file))
    engine = create_engine(f"sqlite:///{db_file}")
    Setting.__table__.create(engine)
    w = World(db_file, cid, engine)
    w.put("sm_newsletter.transport", "console")
    w.put("sm_newsletter.from_address", "news@example.org")
    w.put("sm_newsletter.physical_address", "1 Main Street, Springfield")
    sync_db.set_database_url(f"sqlite:///{db_file}")
    worker.reset_worker_runtime()
    yield w
    worker.reset_worker_runtime()
    sync_db.set_database_url(None)
    sync_db.dispose_sync_engine()
    engine.dispose()
    reset_worker_caches()


@pytest.fixture
def listener():
    """A socket that would accept a relay connection; :func:`connections`
    counts the ones that arrived (they wait in the backlog)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    sock.setblocking(False)
    yield sock
    sock.close()


def connections(sock: socket.socket) -> int:
    count = 0
    while True:
        try:
            conn, _ = sock.accept()
        except BlockingIOError:
            return count
        conn.close()
        count += 1


async def _state_of(db_file: Path, cid: int) -> tuple[str, list[str], int]:
    """The campaign's status, its send rows' statuses and the attempt count."""
    state = await make_db_state(file=db_file)
    try:
        campaign = await campaign_row(state, T, cid)
        rows = [row.status for row in await send_rows(state, T, cid)]
        with tenant_scope(T):
            async with state.session_factory() as db:
                attempts = len((await db.execute(select(SendAttempt.id))).all())
    finally:
        await state.engine.dispose()
    return campaign.status, rows, attempts


def _token(message: console.CapturedMessage) -> str:
    header = message.headers["List-Unsubscribe"]
    return header.split(UNSUBSCRIBE_PREFIX, 1)[1].split(">", 1)[0]


def _refused(world: World, summary: dict[str, Any]) -> None:
    """Nothing happened: no freeze, no attempt, nothing captured."""
    assert summary["stopped"] == "not_configured"
    assert (summary["started"], summary["spent"], summary["recovered"]) == (0, 0, 0)
    assert asyncio.run(_state_of(world.db_file, world.cid)) == ("scheduled", [], 0)
    assert console.captured(T) == []


@pytest.mark.unbound_tenant
def test_dispatch_task_sends_through_the_worker_runtime(world):
    world.put("host.secret_key", SECRET)

    summary = tasks.dispatch()

    assert (summary["started"], summary["spent"]) == (1, 2)
    captured = console.captured(T)
    assert sorted(m.to for m in captured) == ["s0@example.org", "s1@example.org"]
    for message in captured:
        claims = tokens.parse(SECRET, _token(message))
        assert claims is not None
        assert (claims.tenant_id, claims.campaign_id) == (T, world.cid)
    assert asyncio.run(_state_of(world.db_file, world.cid)) == ("sent", ["sent", "sent"], 2)


@pytest.mark.unbound_tenant
def test_dispatch_refuses_without_a_secret(world, caplog):
    with caplog.at_level(logging.ERROR):
        summary = tasks.dispatch()

    _refused(world, summary)
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("SecretMissing" in m for m in errors)


@pytest.mark.unbound_tenant
def test_dispatch_refuses_unreadable_password(world, listener, caplog):
    """S11's fifth case: an ``enc:v1:`` password under another secret is
    refused before any connection, never sent as ciphertext."""
    world.put("host.secret_key", SECRET)
    world.smtp_to(listener.getsockname()[1], encrypted("pw", "another-secret"))

    with caplog.at_level(logging.ERROR):
        summary = tasks.dispatch()

    _refused(world, summary)
    assert connections(listener) == 0
    assert any("SmtpPasswordUnreadable" in r.getMessage() for r in caplog.records)


@pytest.mark.unbound_tenant
def test_dispatch_refuses_a_plaintext_password(world, listener, caplog):
    """A5: a password stored without ``enc:v1:`` is never sent to a relay."""
    world.put("host.secret_key", SECRET)
    world.smtp_to(listener.getsockname()[1], "hunter2")

    with caplog.at_level(logging.DEBUG):
        summary = tasks.dispatch()

    _refused(world, summary)
    assert connections(listener) == 0
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert ENDPOINT in errors[0]
    assert "PlaintextPassword" in errors[0]
    assert not [r for r in caplog.records if "hunter2" in r.getMessage()]


def test_dispatch_task_unbinds_the_callers_tenant(world):
    """Run under the suite's bound ``default``: the tick enumerates tenants
    itself, so the platform pass unbinds it first."""
    world.put("host.secret_key", SECRET)
    assert tasks.dispatch()["spent"] == 2


@pytest.mark.unbound_tenant
def test_no_token_in_any_log(world, caplog):
    """A7: a minted token is a capability; no log line may carry one."""
    world.put("host.secret_key", SECRET)
    caplog.set_level(logging.DEBUG)
    for name in LOGGERS:
        caplog.set_level(logging.DEBUG, logger=name)

    assert tasks.dispatch()["spent"] == 2

    macs = [_token(m).rsplit(".", 1)[1] for m in console.captured(T)]
    assert len(macs) == 2
    lines = [r.getMessage() for r in caplog.records]
    assert any("console transport" in line for line in lines)  # the capture saw the send
    assert not [line for line in lines if UNSUBSCRIBE_PREFIX in line]
    assert not [line for line in lines if any(mac in line for mac in macs)]


def test_unreadable_settings_log_the_causes_class(monkeypatch, caplog):
    """The refusal names the cause's class (a misconfigured worker shows only in
    its logs), never the cause's text."""
    import background_tasks
    from sm_newsletter.sending import runtime

    def broken(*_args: Any, **_kw: Any) -> Any:
        raise ConnectionRefusedError("db.internal:5432 password=hunter2")

    monkeypatch.setattr(background_tasks, "settings_for", broken)
    with caplog.at_level(logging.ERROR):
        summary = asyncio.run(runtime.dispatch_async(None))  # ty: ignore[invalid-argument-type]

    assert summary.stopped == "not_configured"
    [line] = [r.getMessage() for r in caplog.records if "refused" in r.getMessage()]
    assert "SettingsUnreadable" in line and "ConnectionRefusedError" in line
    assert "hunter2" not in line
