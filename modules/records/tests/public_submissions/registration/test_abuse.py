"""The bounds on this route: per IP, per address and the captcha; no per-type budget."""

from __future__ import annotations

import pytest

from tests.support.registration_http import load_registration, register, regs, seed_event
from tests.support.submissions_http import configure

pytestmark = pytest.mark.usefixtures("reg_site")


async def token(site, event):
    return (await load_registration(site, event)).json()["definition"]["token"]


async def test_the_per_ip_limit_and_the_captcha_apply(reg_site, provider):
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
    refused = await register(
        reg_site, "cap@example.org", event=event, token=await token(reg_site, event)
    )
    assert (refused.status_code, refused.json()["code"]) == (400, "captcha_failed")


async def test_there_is_no_per_type_budget_for_registrations(reg_site):
    """The shared per-type budget (60/hour) would let a dozen rotating addresses lock every genuine
    registrant out; a registration is bounded per IP, per address and by the captcha instead."""
    configure(
        reg_site,
        public_submissions_rate_per_ip="1000/minute",
        public_submissions_type_rate="2/hour",
    )
    event = await seed_event(reg_site.db_state, uid="t@x", registration_capacity=10)
    tokens = [await token(reg_site, event) for _ in range(5)]
    got = [
        (await register(reg_site, f"t{n}@example.org", event=event, token=tokens[n])).status_code
        for n in range(5)
    ]
    assert got == [202] * 5 and len(await regs(reg_site)) == 5


async def test_one_address_is_mailed_a_bounded_number_of_times(reg_site):
    """3 mails a day per address and form (records' existing bound); past it the route still
    answers the same 202 and sends nothing."""
    event = await seed_event(reg_site.db_state, uid="m@x", registration_capacity=10)
    tokens = [await token(reg_site, event) for _ in range(5)]
    configure(reg_site, public_submissions_rate_per_ip="1000/minute")
    answers = {
        (await register(reg_site, "same@example.org", event=event, token=tokens[n])).text
        for n in range(5)
    }
    assert answers == {'{"ok":true}'}
    assert len([m for m in reg_site.outbox.sent if m.to == "same@example.org"]) == 3
