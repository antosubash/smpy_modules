"""The submit route never says whether a person is registered (security review).

One answer per event state, whatever the address: a new address, one already pending, one already
registered and one that cancelled are byte-identical on the wire. What happened is told by mail to
that address only. The event-level states (closed, full) answer everyone alike, before anything is
looked up about the person.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event as sa_event

from tests.support.app_harness import ADMIN, roles
from tests.support.registration_http import (
    follow,
    load_registration,
    record_url,
    reg_links,
    register,
    regs,
    seed_event,
    single_opt_in,
)
from tests.support.submissions_http import JSON, SUBMISSIONS

pytestmark = pytest.mark.usefixtures("reg_site")
KEPT = ("content-type", "cache-control")


def shape(resp):
    return (resp.status_code, resp.text, tuple(resp.headers.get(h) for h in KEPT))


async def token(site, event):
    return (await load_registration(site, event)).json()["definition"]["token"]


async def people(site, event):
    """pending p@, confirmed c@, cancelled x@ on ``event``."""
    for who in ("p", "c", "x"):
        await register(site, f"{who}@example.org", event=event)
    mails = {m.to: m for m in site.outbox.sent}
    assert (
        await follow(site, "confirm", reg_links(mails["c@example.org"])["confirm"]["t"])
    ).status_code == 200
    items = {r["data"]["sm_email"]: r for r in await regs(site)}
    cancelled = await site.post(
        record_url(items["x@example.org"]["uuid"], "/submission/cancel"), headers=roles(ADMIN)
    )
    assert cancelled.status_code == 200


async def attempts(site, event, **extra):
    out = {}
    for who in ("new", "p", "c", "x"):
        out[who] = await register(
            site, f"{who}@example.org", event=event, token=TOKENS[who], **extra
        )
    return out


TOKENS: dict[str, str] = {}


async def mint(site, event):
    for who in ("new", "p", "c", "x"):
        TOKENS[who] = await token(site, event)


async def test_open_event_one_answer_for_everyone(reg_site):
    event = await seed_event(reg_site.db_state, uid="o@x", registration_capacity=40)
    await people(reg_site, event)
    await mint(reg_site, event)
    before = len(reg_site.outbox.sent)
    got = await attempts(reg_site, event)
    assert {shape(r) for r in got.values()} == {
        (202, '{"ok":true}', ("application/json", "no-store"))
    }
    sent = {m.to: m for m in reg_site.outbox.sent[before:]}
    assert set(sent) == {"new@example.org", "p@example.org", "c@example.org", "x@example.org"}
    assert "confirm" in reg_links(sent["new@example.org"]) and "confirm" in reg_links(
        sent["p@example.org"]
    )
    assert "confirm" not in reg_links(sent["c@example.org"]) and "cancel" in reg_links(
        sent["c@example.org"]
    )
    assert (
        "already" in sent["c@example.org"].subject.lower()
        or "bereits" in sent["c@example.org"].subject.lower()
    )
    assert "confirm" in reg_links(sent["x@example.org"])  # a cancelled address registers anew


async def test_full_event_one_answer_for_everyone(reg_site):
    event = await seed_event(reg_site.db_state, uid="f@x", registration_capacity=12)
    await people(reg_site, event)  # p, c hold seats (x cancelled): two taken
    await single_opt_in(
        reg_site
    )  # fillers are confirmed at once, so the cap on holds is not in play
    await mint(reg_site, event)
    for n in range(11):  # p holds no seat (pending), c holds one: eleven more fill twelve
        await register(reg_site, f"fill{n}@example.org", event=event, consent=True)
    got = await attempts(reg_site, event, consent=True)
    shapes = {shape(r) for r in got.values()}
    assert len(shapes) == 1 and next(iter(shapes))[0] == 409
    assert '"registration_full"' in next(iter(shapes))[1]


async def test_a_race_for_the_last_seat_is_neutral_too(reg_site, monkeypatch):
    """Single opt-in: full between the availability read and the admit: still the one 202."""
    from sm_records.public_submissions.registration import register as module

    await single_opt_in(reg_site)
    event = await seed_event(reg_site.db_state, uid="r@x", registration_capacity=1)
    await mint(reg_site, event)  # tokens come from an open event
    await register(reg_site, "holder@example.org", event=event, consent=True)
    monkeypatch.setattr(module, "_availability_refusal", lambda state: None)  # the stale read
    before = len(reg_site.outbox.sent)
    new = await register(
        reg_site, "new@example.org", event=event, token=TOKENS["new"], consent=True
    )
    dup = await register(
        reg_site, "holder@example.org", event=event, token=TOKENS["p"], consent=True
    )
    assert shape(new) == shape(dup) and new.status_code == 202
    sent = {m.to: m for m in reg_site.outbox.sent[before:]}
    assert "new@example.org" in sent and "confirm" not in reg_links(sent["new@example.org"])
    assert [r["data"]["sm_email"] for r in await regs(reg_site)] == ["holder@example.org"]


async def test_statement_counts_match_between_branches(reg_site):
    """The duplicate branch does the same events work (describe, an idempotent admit)."""
    event = await seed_event(reg_site.db_state, uid="s@x", registration_capacity=20)
    await register(reg_site, "p@example.org", event=event)
    tokens = [await token(reg_site, event) for _ in range(2)]
    engine = reg_site.db_state.engine.sync_engine

    async def counted(address, tok):
        seen: list[str] = []

        def spy(_c, _cur, statement, *_r):
            seen.append(statement)

        sa_event.listen(engine, "before_cursor_execute", spy)
        try:
            await register(reg_site, address, event=event, token=tok)
        finally:
            sa_event.remove(engine, "before_cursor_execute", spy)
        return seen

    new, dup = (
        await counted("new@example.org", tokens[0]),
        await counted("p@example.org", tokens[1]),
    )
    events_new = [s for s in new if "events_" in s]
    events_dup = [s for s in dup if "events_" in s]
    assert abs(len(events_new) - len(events_dup)) <= 1, (len(events_new), len(events_dup))
    assert abs(len(new) - len(dup)) <= max(40, len(new) // 2), (len(new), len(dup))
    assert JSON and SUBMISSIONS and single_opt_in
