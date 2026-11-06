"""Only a double opt-in confirmation - records' confirm link - clears suppressions.

On a single-opt-in list anyone can type a victim's address and the new record
is ``confirmed`` at once, so such a confirmation proves nothing about the
mailbox and must not lift a bounce or an opt-out. The confirm link is the one
``pending -> confirmed`` transition records announces; the signup and the link
below go through records' own code, not hand-made events.
"""

from __future__ import annotations

from typing import Any

import pytest
from simple_module_core.events import EventBus
from simple_module_db import finalize_session
from sm_newsletter.core.suppression import suppress
from sm_newsletter.core.suppression.mirror import apply
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression
from sm_records.contracts.events import SubscriptionChanged
from sqlalchemy import select

from tests.support.records_seed import LIST, confirm_link, seed_list, seed_subscriber, signup

ADA = "ada@example.org"
OTHER = "other"


def _recording_bus() -> tuple[EventBus, list[SubscriptionChanged]]:
    bus, seen = EventBus(), []

    async def note(event: SubscriptionChanged) -> None:
        seen.append(event)

    bus.subscribe(SubscriptionChanged, note)
    return bus, seen


async def _seed_rows(db_state, *rows: tuple[str, str]) -> None:
    """``(reason, list_type_key)`` rows for ADA, recorded now."""
    async with db_state.session_factory() as s:
        for reason, key in rows:
            await suppress(
                s,
                tenant_id="default",
                email=ADA,
                reason=reason,
                source="admin",
                list_type_key=key,
            )
        await finalize_session(s)


async def _rows(db_state) -> list[tuple[str, str]]:
    with tenant_scope("default"):
        async with db_state.session_factory() as s:
            rows = (await s.execute(select(Suppression).order_by(Suppression.id))).scalars()
            return [(r.reason, r.list_type_key) for r in rows]


EVERY_ROW = [
    ("unsubscribed", OTHER),
    ("unsubscribed", LIST),
    ("hard_bounce", ""),
    ("imported_cleaned", ""),
    ("complaint", ""),
]


async def test_single_opt_in_signup_clears_nothing(db_state):
    """A brand-new address on a single-opt-in list: records confirms it at
    once (``None -> confirmed``); every row - another list's opt-out, this
    list's left over from a purged record, the bounces - is kept."""
    await seed_list(db_state, "default", double_opt_in=False)
    await _seed_rows(db_state, *EVERY_ROW)
    bus, seen = _recording_bus()
    await signup(db_state, "default", ADA, bus)
    assert [(e.status_before, e.status_after) for e in seen] == [(None, "confirmed")]
    assert await apply(seen[0], db_state.session_factory) == "ignored"
    assert await _rows(db_state) == EVERY_ROW


async def test_single_opt_in_signup_through_the_wired_handler(db_state):
    from types import SimpleNamespace

    from sm_newsletter.module import NewsletterModule

    bus = EventBus()
    app = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=db_state, event_bus=bus)))
    NewsletterModule().register_event_handlers(bus, app)
    await seed_list(db_state, "default", double_opt_in=False)
    await _seed_rows(db_state, *EVERY_ROW)
    await signup(db_state, "default", ADA, bus)
    assert await _rows(db_state) == EVERY_ROW


async def test_single_opt_in_resignup_of_a_known_address_is_pending(db_state):
    """Records never puts a known address straight back to confirmed: it goes
    to ``pending`` (``subscribe._write``), and nothing is cleared."""
    await seed_list(db_state, "default", double_opt_in=False)
    await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    await _seed_rows(db_state, ("unsubscribed", LIST), ("hard_bounce", ""))
    bus, seen = _recording_bus()
    await signup(db_state, "default", ADA, bus)
    assert [(e.status_before, e.status_after) for e in seen] == [("unsubscribed", "pending")]
    assert await apply(seen[0], db_state.session_factory) == "ignored"
    assert await _rows(db_state) == [("unsubscribed", LIST), ("hard_bounce", "")]


async def test_double_opt_in_confirm_link_clears(db_state):
    await seed_list(db_state, "default", double_opt_in=True)
    await _seed_rows(db_state, *EVERY_ROW)
    bus, seen = _recording_bus()
    uuid = await signup(db_state, "default", ADA, bus)
    assert [(e.status_before, e.status_after) for e in seen] == [(None, "pending")]
    assert await apply(seen[0], db_state.session_factory) == "ignored"
    assert await _rows(db_state) == EVERY_ROW

    assert await confirm_link(db_state, "default", uuid, bus) == "confirmed"
    assert [(e.status_before, e.status_after) for e in seen[1:]] == [("pending", "confirmed")]
    assert await apply(seen[1], db_state.session_factory) == "cleared"
    assert await _rows(db_state) == [("unsubscribed", OTHER), ("complaint", "")]


@pytest.mark.parametrize("before", [None, "confirmed", "unsubscribed"])
async def test_confirmed_not_from_pending_is_ignored(db_state, before: Any):
    """Whatever the subscriber holds, only ``pending -> confirmed`` is the
    confirm link; any other way to ``confirmed`` clears nothing."""
    await seed_list(db_state, "default")
    await _seed_rows(db_state, ("unsubscribed", LIST), ("hard_bounce", ""))
    u = await seed_subscriber(db_state, "default", ADA, "confirmed")
    event = SubscriptionChanged(
        type_key=LIST, tenant_id="default", uuid=u, status_before=before, status_after="confirmed"
    )
    assert await apply(event, db_state.session_factory) == "ignored"
    assert await _rows(db_state) == [("unsubscribed", LIST), ("hard_bounce", "")]
