"""An unconfirmed registration cannot hold seats for long, nor take too many (security review)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_records.public_submissions.registration import holds

from tests.support.public_submissions_support import update as update_type
from tests.support.registration_http import (
    TYPE,
    follow,
    load_registration,
    reg_config,
    reg_links,
    register,
    regs,
    seat_counts,
    seed_event,
)
from tests.support.submissions_http import configure

pytestmark = pytest.mark.usefixtures("reg_site")


async def token(site, event):
    return (await load_registration(site, event)).json()["definition"]["token"]


async def test_an_expired_hold_is_released_when_the_next_person_needs_the_seat(
    reg_site, monkeypatch
):
    event = await seed_event(reg_site.db_state, uid="h@x", registration_capacity=4)
    tokens = [await token(reg_site, event) for _ in range(3)]
    await register(reg_site, "a@example.org", event=event, token=tokens[0])
    await register(reg_site, "b@example.org", event=event, token=tokens[1])
    assert await seat_counts(reg_site) == (2, 2)
    later = datetime.now(UTC) + timedelta(hours=2)  # the default hold is one hour
    monkeypatch.setattr(holds, "_now", lambda: later)
    got = await register(reg_site, "c@example.org", event=event, token=tokens[2])
    assert got.status_code == 202
    assert [r["data"]["sm_email"] for r in await regs(reg_site)] == ["c@example.org"]
    assert await seat_counts(reg_site) == (1, 1)


async def test_a_confirmed_registration_is_never_expired(reg_site, monkeypatch):
    event = await seed_event(reg_site.db_state, uid="k@x", registration_capacity=4)
    tokens = [await token(reg_site, event) for _ in range(3)]
    await register(reg_site, "keep@example.org", event=event, token=tokens[0])
    mail = next(m for m in reg_site.outbox.sent if m.to == "keep@example.org")
    assert (await follow(reg_site, "confirm", reg_links(mail)["confirm"]["t"])).status_code == 200
    await register(reg_site, "drop@example.org", event=event, token=tokens[1])
    monkeypatch.setattr(holds, "_now", lambda: datetime.now(UTC) + timedelta(days=3))
    await register(reg_site, "next@example.org", event=event, token=tokens[2])
    emails = sorted(r["data"]["sm_email"] for r in await regs(reg_site))
    assert emails == ["keep@example.org", "next@example.org"]
    assert await seat_counts(reg_site) == (2, 2)


async def test_unconfirmed_holds_are_capped_per_occurrence(reg_site):
    configure(
        reg_site,
        public_submissions_rate_per_ip="1000/minute",
        public_submissions_type_rate="1000/minute",
        public_submissions_confirm_rate_per_email="1000/day",
    )
    event = await seed_event(reg_site.db_state, uid="c@x", registration_capacity=10)
    cap = holds.pending_cap(10)
    assert cap == 5 and holds.pending_cap(None) == holds.MAX_PENDING and holds.pending_cap(1) == 1
    tokens = [await token(reg_site, event) for _ in range(30)]
    answers = set()
    for n in range(30):
        resp = await register(reg_site, f"p{n}@example.org", event=event, token=tokens[n])
        answers.add((resp.status_code, resp.text))
    assert answers == {(202, '{"ok":true}')}, "the cap is never a different answer"
    items = await regs(reg_site)
    assert len(items) == cap and (await seat_counts(reg_site))[0] == cap
    # the people turned away were told so by mail, not by the form
    told = [m for m in reg_site.outbox.sent if "confirm" not in reg_links(m)]
    assert len(told) == 30 - cap


async def test_the_cap_never_blocks_single_opt_in_confirmed_registrations(reg_site):
    await update_type(
        reg_site,
        TYPE,
        public_submissions=reg_config(
            double_opt_in=False, consent={"required": True, "text": {"en": "ok"}}
        ),
    )
    configure(reg_site, public_submissions_rate_per_ip="1000/minute",
              public_submissions_type_rate="1000/minute")  # fmt: skip
    event = await seed_event(reg_site.db_state, uid="s@x", registration_capacity=10)
    tokens = [await token(reg_site, event) for _ in range(8)]
    for n in range(8):
        await register(reg_site, f"r{n}@example.org", event=event, token=tokens[n], consent=True)
    assert len(await regs(reg_site)) == 8


async def test_the_per_ip_limit_and_the_captcha_apply_to_this_branch(reg_site, provider):
    configure(reg_site, public_submissions_rate_per_ip="2/minute")
    event = await seed_event(reg_site.db_state, uid="i@x", registration_capacity=10)
    tokens = [await token(reg_site, event) for _ in range(3)]
    codes = [
        (await register(reg_site, f"i{n}@example.org", event=event, token=tokens[n])).status_code
        for n in range(3)
    ]
    assert codes == [202, 202, 429]
    configure(
        reg_site,
        public_submissions_rate_per_ip="1000/minute",
        public_submissions_captcha_provider="turnstile",
        public_submissions_captcha_site_key="k",
        public_submissions_captcha_secret="s",
    )
    fresh = await token(reg_site, event)
    refused = await register(reg_site, "cap@example.org", event=event, token=fresh)
    assert (refused.status_code, refused.json()["code"]) == (400, "captcha_failed")
