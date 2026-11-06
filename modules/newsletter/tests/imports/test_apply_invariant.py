"""The HARD invariant, newsletter's half (Review Focus 2, D1, R5).

A subscribed row that newsletter suppresses, or that records holds unsubscribed on any list
of the tenant, is never handed to records; no suppression is ever cleared; and the import
announces nothing, so the mirror never sees ``pending -> confirmed``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from simple_module_core.events import EventBus
from sm_newsletter.core import suppression
from sm_newsletter.core.suppression import mirror, store
from sm_newsletter.imports import apply
from sm_records.contracts.events import SubscriptionChanged
from sm_records.core import events

from tests.imports.world import FIELDS, upload
from tests.support.app import build_app
from tests.support.import_world import (
    CLEAN,
    NOW,
    SUB,
    UNSUB,
    apply_now,
    outcomes,
    queued,
    records_of,
    run_all,
    suppress_at,
    suppression_rows,
)
from tests.support.records_seed import seed_list, seed_subscriber, signup

pytestmark = pytest.mark.unbound_tenant

ADA, BOB, EVE = (f"{n}@example.org" for n in ("ada", "bob", "eve"))


@pytest_asyncio.fixture
async def state(tmp_path):
    _app, st = await build_app(file=tmp_path / "apply.db")
    await seed_list(st, "default", fields=FIELDS)
    yield st
    await st.engine.dispose()


async def test_import_clears_no_suppression(state):
    earlier = NOW - timedelta(days=30)
    await suppress_at(state, ADA, "hard_bounce", at=earlier)
    await suppress_at(state, BOB, "imported_cleaned", at=earlier)
    await suppress_at(state, EVE, "complaint", at=earlier)
    before = await suppression_rows(state)
    jid = await queued(
        state, upload(SUB, [[ADA, "", "", ""], [BOB, "", "", ""], [EVE, "", "", ""]])
    )
    result = await apply_now(state, jid)
    assert await suppression_rows(state) == before
    assert (result.created, result.skipped) == (0, 3)
    assert set((await outcomes(state, jid)).values()) == {"skipped_suppressed"}
    assert await records_of(state) == {}


async def test_suppressed_address_is_never_created(state):
    await suppress_at(state, ADA, "unsubscribed", key="other")
    jid = await queued(state, upload(SUB, [[ADA, "Ada", "", ""]]))
    result = await apply_now(state, jid)
    assert result.skipped == 1
    assert ADA not in await records_of(state)


async def test_opted_out_in_records_without_mirror_row_is_skipped(state, monkeypatch):
    await seed_list(state, "default", "other", fields=FIELDS)
    await seed_subscriber(state, "default", ADA, "unsubscribed", "other")
    assert await suppression_rows(state) == []  # the mirror never ran
    handed: list[str] = []
    real = apply.import_subscribers

    async def spy(session, **kw):
        handed.extend(r.email for r in kw["rows"])
        return await real(session, **kw)

    monkeypatch.setattr(apply, "import_subscribers", spy)
    jid = await queued(state, upload(SUB, [[ADA, "Ada", "", ""], [BOB, "Bob", "", ""]]))
    result = await apply_now(state, jid)
    assert (result.created, result.skipped) == (1, 1)
    assert handed == [BOB]
    assert ADA not in await records_of(state)
    assert (await outcomes(state, jid))[ADA] == "skipped_suppressed"


async def test_no_pending_to_confirmed_event(state, monkeypatch):
    from types import SimpleNamespace

    from sm_newsletter.module import NewsletterModule

    bus, seen = EventBus(), []

    async def note(event):
        seen.append(event)

    bus.subscribe(SubscriptionChanged, note)
    app = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=state, event_bus=bus)))
    NewsletterModule().register_event_handlers(bus, app)
    await signup(state, "default", ADA, bus)
    assert [(e.status_before, e.status_after) for e in seen] == [(None, "pending")]
    seen.clear()

    async def never(*_a, **_kw):
        raise AssertionError("an import must never clear a suppression")

    for module in (suppression, store, mirror):
        monkeypatch.setattr(module, "clear_for_confirmation", never)

    def factory():
        session = state.session_factory()
        events.attach(session, bus)
        return session

    jid = await queued(state, upload(SUB, [[ADA, "Ada", "", ""], [BOB, "Bob", "", ""]]))
    assert await run_all(factory, jid) == ["done"]
    assert seen == []
    records = await records_of(state)
    assert records[ADA].data["sm_status"] == "pending"
    assert records[BOB].data["sm_status"] == "confirmed"


@pytest.mark.parametrize("existing", ["hard_bounce", "complaint"])
@pytest.mark.parametrize(
    ("name", "reason", "key"),
    [(UNSUB, "unsubscribed", "news"), (CLEAN, "imported_cleaned", "")],
)
async def test_different_reason_suppression_is_left_alone(state, existing, name, reason, key):
    earlier = NOW - timedelta(days=30)
    await suppress_at(state, ADA, existing, at=earlier)  # address-wide reasons carry no list key
    before = await suppression_rows(state)
    jid = await queued(state, upload(name, [[ADA, "", "", ""]]))
    await apply_now(state, jid)
    after = await suppression_rows(state)
    assert all(row in after for row in before)  # reason, source and created_at unchanged
    added = [row for row in after if row not in before]
    assert [(r[1], r[2], r[3]) for r in added] == [(reason, key, "import")]
