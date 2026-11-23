"""Calling a provider: bounded, on a connection of its own, and never trusted (PR 9).

Which of the contract's calls share events' transaction: none of these. A provider call runs on
the plugin runner's own connection (or, on the in-memory test engine, in a rolled-back savepoint),
so it can read committed data only and can never write.
"""

from __future__ import annotations

import pytest
from sm_events.contracts.extensions import (
    Registrant,
    RegistrationTargetError,
    RegistrationTargetInfo,
)
from sm_events.core import constants
from sm_events.core.errors_registration import RegistrationUnavailable, UnknownRegistrationTarget
from sm_events.models import Calendar
from sm_events.registration import provider_call
from sqlalchemy import select

from tests.support.providers import KNOWN_TARGET, provider, slow


async def test_check_target_answers(db):
    info = await provider_call.check_target(
        provider(), db=db, tenant_id="default", target=KNOWN_TARGET
    )
    assert info == RegistrationTargetInfo(
        "Event registrations",
        "/admin/records/event-registrations",
        "/admin/records/event-registrations?filter=x",
    )


async def test_unknown_target(db):
    with pytest.raises(UnknownRegistrationTarget):
        await provider_call.check_target(provider(), db=db, tenant_id="default", target="nope")


async def test_check_target_timeout(db, monkeypatch):
    monkeypatch.setattr(constants, "SOURCE_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(RegistrationUnavailable) as caught:
        await provider_call.check_target(
            provider(check=slow), db=db, tenant_id="default", target=KNOWN_TARGET
        )
    assert caught.value.status_code == 503
    # the savepoint was rolled back: the session is still usable
    assert (await db.execute(select(Calendar))).scalars().all() == []


async def test_provider_write_refused(db):
    async def writer(ctx, target):
        ctx.db.add(Calendar(slug="sneaky", name="Sneaky", owner_id="o"))
        await ctx.db.flush()
        return RegistrationTargetInfo("x", None, None)

    with pytest.raises(RegistrationUnavailable) as caught:
        await provider_call.check_target(
            provider(check=writer), db=db, tenant_id="default", target=KNOWN_TARGET
        )
    assert caught.value.status_code == 503
    assert (await db.execute(select(Calendar))).scalars().all() == []


async def test_a_crashing_provider_is_unavailable_and_says_nothing(db, caplog):
    async def boom(ctx, target):
        raise RuntimeError("secret detail ann@example.com")

    with caplog.at_level("DEBUG"), pytest.raises(RegistrationUnavailable):
        await provider_call.check_target(
            provider(check=boom), db=db, tenant_id="default", target=KNOWN_TARGET
        )
    assert "ann@example.com" not in caplog.text and "secret detail" not in caplog.text


@pytest.mark.parametrize(
    "answer",
    [None, "x", RegistrationTargetInfo("x", "https://evil.example", None),
     RegistrationTargetInfo("x", None, "//evil.example"),
     RegistrationTargetInfo("", None, None)],
)  # fmt: skip
async def test_a_malformed_answer_is_unavailable(db, answer):
    async def odd(ctx, target):
        return answer

    with pytest.raises(RegistrationUnavailable):
        await provider_call.check_target(
            provider(check=odd), db=db, tenant_id="default", target=KNOWN_TARGET
        )


async def test_recipients(db):
    got = await provider_call.recipients(provider(), db=db, tenant_id="default", holders=["a", "b"])
    assert got == {
        "a": Registrant("a@example.com", "a", "en"),
        "b": Registrant("b@example.com", "b", "en"),
    }
    assert await provider_call.recipients(provider(), db=db, tenant_id="default", holders=[]) == {}


async def test_recipients_only_for_holders_asked(db):
    async def greedy(ctx, holders):
        return {"a": Registrant("a@x.org", "A", "en"), "z": Registrant("z@x.org", "Z", "en")}

    got = await provider_call.recipients(
        provider(recipients=greedy), db=db, tenant_id="default", holders=["a"]
    )
    assert list(got) == ["a"]


async def test_recipients_failure(db, monkeypatch):
    async def slow_recipients(ctx, holders):
        import asyncio

        await asyncio.sleep(10)

    monkeypatch.setattr(constants, "SOURCE_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(RegistrationUnavailable):
        await provider_call.recipients(
            provider(recipients=slow_recipients), db=db, tenant_id="default", holders=["a"]
        )


async def test_target_error_type_is_a_plain_exception():
    assert str(RegistrationTargetError("m")) == "m"
