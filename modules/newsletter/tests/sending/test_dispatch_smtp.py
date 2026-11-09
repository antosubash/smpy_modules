"""One dispatcher tick end to end over real SMTP (the aiosmtpd relay of ``conftest``).

``ok@`` is accepted, ``bounce@`` refused ``550 5.1.1`` at RCPT (a bounce) and
``soft@`` deferred ``451 4.3.0`` after DATA: a retry that does not stop the
tick (S4: only ``421`` or a ``4.7.x`` quota reply does).
"""

from __future__ import annotations

import email
import logging
from email.message import Message

import pytest
from sm_newsletter.core.constants import UNSUBSCRIBE_PREFIX
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression
from sqlalchemy import select

from tests.support.campaign_world import campaign_row, send_rows
from tests.support.deliver_world import SECRET
from tests.support.dispatch_world import run_tick, world
from tests.support.freeze_world import due_campaign
from tests.support.records_seed import seed_subscriber
from tests.support.sending import BASE_URL, T

pytestmark = pytest.mark.unbound_tenant

OK, BOUNCE, SOFT = "ok@example.org", "bounce@example.org", "soft@example.org"
WATCHED = ("sm_newsletter", "aiosmtplib", "celery")


@pytest.fixture
async def built(tmp_path):
    app, state, _ = await world(tmp_path)
    yield app, state
    await state.engine.dispose()


async def _reasons(state) -> list[str]:
    with tenant_scope(T):
        async with state.session_factory() as db:
            stmt = select(Suppression.reason).where(Suppression.tenant_id == T)
            return list((await db.execute(stmt)).scalars())


async def test_one_tick_over_smtp(built, relay, make_transport, caplog):
    app, state = built
    _, recorder = relay
    for address in (OK, BOUNCE, SOFT):
        await seed_subscriber(state, T, address, "confirmed")
    cid = await due_campaign(state)
    for name in WATCHED:
        caplog.set_level(logging.DEBUG, logger=name)

    summary = await run_tick(app, state, make_transport())

    assert (summary.started, summary.spent, summary.stopped) == (1, 3, "idle")
    (envelope,) = recorder.delivered
    assert envelope.rcpt_tos == [OK]
    message: Message = email.message_from_bytes(envelope.content)
    unsubscribe = message["List-Unsubscribe"]
    assert unsubscribe.startswith(f"<{BASE_URL}{UNSUBSCRIBE_PREFIX}")
    assert unsubscribe.endswith(">")
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert message["Precedence"] == "bulk"

    rows = {row.email: row for row in await send_rows(state, T, cid)}
    assert rows[OK].status == "sent"
    assert rows[BOUNCE].status == "bounced"
    assert (rows[SOFT].status, rows[SOFT].retry_at is not None) == ("queued", True)
    assert await _reasons(state) == ["hard_bounce"]
    assert (await campaign_row(state, T, cid)).status == "sending"  # soft@ is still due

    # A7 on the real transport: aiosmtplib and the dispatcher log no token.
    mac = unsubscribe[1:-1].rsplit(".", 1)[1]
    lines = [r.getMessage() for r in caplog.records if r.name.startswith(WATCHED)]
    assert not [line for line in lines if UNSUBSCRIBE_PREFIX in line or mac in line]
    assert SECRET not in caplog.text
