"""The bounds on this route: per IP, per form total, per address and the captcha."""

from __future__ import annotations

import pytest

from tests.support.registration_http import (
    confirm_record,
    load_registration,
    register,
    regs,
    seed_event,
)
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


async def test_the_form_total_limit_applies_to_registrations(reg_site):
    """The per-form total (``public_submissions_type_rate``, every submission form has one) bounds
    a distributed sender: without it the route could create unbounded pending records and mail
    unbounded distinct third-party addresses. Over it: the same 429 every form answers, identical
    for every address; confirm and cancel are not counted."""
    configure(
        reg_site,
        public_submissions_rate_per_ip="1000/minute",
        public_submissions_type_rate="2/hour",
    )
    event = await seed_event(reg_site.db_state, uid="t@x", registration_capacity=10)
    tokens = [await token(reg_site, event) for _ in range(4)]
    got = [
        await register(reg_site, f"t{n}@example.org", event=event, token=tokens[n])
        for n in range(4)
    ]
    assert [g.status_code for g in got] == [202, 202, 429, 429]
    assert all("Retry-After" in g.headers for g in got[2:])
    assert got[2].json() == got[3].json()  # no address-dependent difference
    assert len(await regs(reg_site)) == 2
    # a confirmation or a cancel is not a submit: the holder of a link can always use it
    first = (await regs(reg_site))[0]
    assert (await confirm_record(reg_site, first)).status_code == 200


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


async def test_the_form_total_is_charged_only_after_the_captcha_passes(reg_site):
    """N submits that fail the captcha leave the form's total untouched: burning it costs one
    solved captcha per request."""
    configure(
        reg_site,
        public_submissions_rate_per_ip="1000/minute",
        public_submissions_type_rate="2/hour",
        public_submissions_captcha_provider="turnstile",
        public_submissions_captcha_site_key="k",
        public_submissions_captcha_secret="s",
    )
    event = await seed_event(reg_site.db_state, uid="c@x", registration_capacity=10)
    for n in range(5):
        refused = await register(
            reg_site, f"c{n}@example.org", event=event, token=await token(reg_site, event)
        )
        assert (refused.status_code, refused.json()["code"]) == (400, "captcha_failed")
    configure(
        reg_site,
        public_submissions_rate_per_ip="1000/minute",
        public_submissions_type_rate="2/hour",
        public_submissions_captcha_provider="none",
    )
    got = [
        (
            await register(
                reg_site, f"v{n}@example.org", event=event, token=await token(reg_site, event)
            )
        )
        for n in range(3)
    ]
    assert [g.status_code for g in got] == [202, 202, 429]
    assert got[2].headers.get("Retry-After")


class Counting:
    """Counts the captcha provider calls and the pattern worker runs, and accepts one answer."""

    def __init__(self, monkeypatch):
        from sm_records.public_submissions import submit as module
        from sm_records.public_submissions.errors import SubmissionRefused

        self.provider = 0
        self.patterns = 0
        real = module.check_patterns

        async def verify(settings, response, ip):
            self.provider += 1
            if settings.public_submissions_captcha_provider != "none" and response != "good":
                raise SubmissionRefused("captcha_failed", "captcha failed")

        async def patterns(*args, **kwargs):
            self.patterns += 1
            return await real(*args, **kwargs)

        monkeypatch.setattr(module.captcha, "verify", verify)
        monkeypatch.setattr(module, "check_patterns", patterns)


def limits(**extra):
    return {
        "public_submissions_rate_per_ip": "10000/minute",
        "public_submissions_type_rate": "2/hour",
        **extra,
    }


CAPTCHA = {
    "public_submissions_captcha_provider": "turnstile",
    "public_submissions_captcha_site_key": "k",
    "public_submissions_captcha_secret": "s",
}


async def send(site, event, n, answer):
    return await register(
        site,
        f"f{n}@example.org",
        event=event,
        token=await token(site, event),
        captcha_response=answer,
    )


async def test_a_wrong_captcha_flood_stops_at_the_attempts_bucket(reg_site, monkeypatch):
    """Before the provider is called, a separate higher bucket bounds the attempts; the strict form
    total is not touched, so a real registrant with a right answer still gets in."""
    from sm_records.public_submissions.abuse import ATTEMPTS_MULTIPLE

    counts = Counting(monkeypatch)
    configure(reg_site, **limits(**CAPTCHA))
    event = await seed_event(reg_site.db_state, uid="fl@x", registration_capacity=50)
    cap = 2 * ATTEMPTS_MULTIPLE
    codes = [(await send(reg_site, event, n, "bad")).status_code for n in range(cap + 5)]
    assert codes == [400] * cap + [429] * 5
    assert counts.provider == cap  # the provider was called no more than the bucket allows
    assert counts.patterns == 0


async def test_a_right_answer_still_gets_in_after_wrong_ones(reg_site, monkeypatch):
    counts = Counting(monkeypatch)
    configure(reg_site, **limits(**CAPTCHA))
    event = await seed_event(reg_site.db_state, uid="ok@x", registration_capacity=50)
    for n in range(8):
        assert (await send(reg_site, event, n, "bad")).status_code == 400
    got = [(await send(reg_site, event, 100 + n, "good")).status_code for n in range(3)]
    assert got == [202, 202, 429]  # the strict total (2) counted only the right answers
    assert counts.patterns == 2


async def test_without_a_captcha_the_strict_budget_is_charged_first(reg_site, monkeypatch):
    counts = Counting(monkeypatch)
    configure(reg_site, **limits(public_submissions_type_rate="1/hour"))
    event = await seed_event(reg_site.db_state, uid="nc@x", registration_capacity=50)
    assert (await send(reg_site, event, 1, None)).status_code == 202
    before = (counts.provider, counts.patterns)
    assert (await send(reg_site, event, 2, None)).status_code == 429
    assert (counts.provider, counts.patterns) == before  # refused before any costly step
