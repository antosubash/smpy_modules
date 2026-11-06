"""``/newsletter/u/<token>``: the unsubscribe page and RFC 8058's one-click POST (S8, S9).

Every answer is the same 200 page whatever the token - real, ``test``, forged,
already used, outdated by a re-signup - so the page is no oracle. Only a POST
with a genuine token for a current subscriber changes anything.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import pytest
from simple_module_core.i18n import I18nRegistry
from sm_newsletter.core import constants, tokens
from sm_records.contracts.newsletter import unsubscribe
from sm_records.core import events as records_events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope as records_scope
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service

from tests.support.records_seed import LIST, confirm_link, set_list_kind, signup
from tests.support.unsub_world import (
    ONE_CLICK,
    app_with,
    call,
    counters,
    sent_campaign,
    snapshot,
    status_of,
    suppressions,
)

pytestmark = pytest.mark.unbound_tenant

T = "default"
ADA = "ada@example.org"
LOCALES = Path(str(importlib.resources.files("sm_newsletter") / "locales"))
UNSUBSCRIBED = [(constants.REASON_UNSUBSCRIBED, LIST, constants.SOURCE_UNSUBSCRIBE_PAGE)]


@pytest.fixture
async def world():
    app, state, events = await app_with()
    sent = await sent_campaign(state, T, ADA)
    yield app, state, events, sent
    await state.engine.dispose()


async def test_get_page_has_button_and_changes_nothing(world):
    app, state, events, s = world
    res = await call(app, "GET", s.token)
    assert res.status_code == 200
    assert '<form method="post"' in res.text
    assert "<script" not in res.text
    assert await status_of(state, s) == "confirmed"
    assert await suppressions(state, T) == []
    assert events == []


async def test_get_is_identical_for_real_test_and_forged(world):
    app, _, _, s = world
    bodies = {
        (await call(app, "GET", t)).content
        for t in (s.token, constants.TEST_UNSUBSCRIBE_TOKEN, "x.1.1.AAAA")
    }
    assert len(bodies) == 1


async def test_one_click_post_unsubscribes(world):
    app, state, events, s = world
    res = await call(app, "POST", s.token, data=ONE_CLICK)
    assert res.status_code == 200
    assert "<form" not in res.text
    assert await status_of(state, s) == "unsubscribed"
    assert await suppressions(state, T) == UNSUBSCRIBED
    assert (await counters(state, s))["unsubscribe_count"] == 1
    assert [(e.uuid, e.status_after) for e in events] == [(s.uuid, "unsubscribed")]


async def test_button_post_with_empty_body_unsubscribes(world):
    app, state, _, s = world
    assert (await call(app, "POST", s.token)).status_code == 200
    assert await status_of(state, s) == "unsubscribed"
    assert await suppressions(state, T) == UNSUBSCRIBED
    assert (await counters(state, s))["unsubscribe_count"] == 1


async def test_post_is_idempotent(world):
    app, state, events, s = world
    first = await call(app, "POST", s.token, data=ONE_CLICK)
    second = await call(app, "POST", s.token, data=ONE_CLICK)
    assert first.content == second.content
    assert (await counters(state, s))["unsubscribe_count"] == 1
    assert await suppressions(state, T) == UNSUBSCRIBED
    assert len(events) == 1


async def test_old_link_after_resignup_changes_nothing(world):
    """Review Focus 3: the person signed up and confirmed again after the mail."""
    app, state, events, s = world
    any_post_page = (await call(app, "POST", "x.1.1.AAAA")).content
    # Left the list some other way (records' own link), then came back.
    with records_scope(T):
        async with state.session_factory() as db:
            assert await unsubscribe(
                db,
                tenant_id=T,
                type_key=LIST,
                uuid=s.uuid,
                unless_confirmed_after=None,
                settings=RecordsSettings(),
            )
            await records_events.commit(db)
    assert await signup(state, T, ADA, app.state.sm.event_bus) == s.uuid
    assert await confirm_link(state, T, s.uuid, app.state.sm.event_bus) == "confirmed"
    events.clear()

    res = await call(app, "POST", s.token, data=ONE_CLICK)
    assert res.content == any_post_page
    assert await status_of(state, s) == "confirmed"
    assert await suppressions(state, T) == []
    assert (await counters(state, s))["unsubscribe_count"] == 0
    assert events == []


async def test_forged_and_test_tokens_change_nothing(world):
    app, state, events, s = world
    real_tenant, real_campaign, real_send, mac = s.token.rsplit(".", 3)
    tampered = f"{real_tenant}.{real_campaign}.{real_send}.{'A' * len(mac)}"
    other_secret = tokens.sign(
        "another-secret", purpose="u", tenant_id=T, campaign_id=s.campaign_id, send_id=s.send_id
    )
    unknown_send = tokens.sign(
        app.state.sm.settings.secret_key,
        purpose="u",
        tenant_id=T,
        campaign_id=s.campaign_id,
        send_id=987654,
    )
    too_long = "a" * (tokens.MAX_TOKEN + 1)
    before = await snapshot(state, s)
    pages = {
        (await call(app, "POST", t, data=ONE_CLICK)).content
        for t in (tampered, constants.TEST_UNSUBSCRIBE_TOKEN, other_secret, unknown_send, too_long)
    }
    assert await snapshot(state, s) == before
    assert events == []
    pages.add((await call(app, "POST", s.token, data=ONE_CLICK)).content)
    assert len(pages) == 1


async def test_deleted_record_is_still_suppressed(world):
    app, state, events, s = world
    settings = RecordsSettings()
    with records_scope(T):
        async with state.session_factory() as db:
            rtype = await type_service.get_type(db, LIST)
            record = await record_service.get_record(db, rtype, s.uuid)
            await record_service.soft_delete_record(db, rtype, record, settings=settings)
            await record_service.hard_delete_record(db, rtype, record)
            await records_events.commit(db)

    assert (await call(app, "POST", s.token, data=ONE_CLICK)).status_code == 200
    assert await suppressions(state, T) == UNSUBSCRIBED
    assert (await counters(state, s))["unsubscribe_count"] == 0
    assert events == []


async def test_list_no_longer_a_list_is_still_suppressed(world):
    app, state, _, s = world
    await set_list_kind(state, T, LIST, "form")
    assert (await call(app, "POST", s.token, data=ONE_CLICK)).status_code == 200
    assert await suppressions(state, T) == UNSUBSCRIBED
    assert (await counters(state, s))["unsubscribe_count"] == 0


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_headers_no_store_no_referrer_noindex(world, method):
    app, _, _, s = world
    res = await call(app, method, s.token)
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/html; charset=utf-8"
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["x-robots-tag"] == "noindex"
    assert res.headers["content-language"] == "en"


async def test_page_language_follows_host_default(world):
    app, _, _, s = world
    registry = I18nRegistry("de", ["en", "de"])
    registry.add_source("newsletter", LOCALES)
    registry.load()
    app.state.sm.i18n_registry = registry
    app.state.sm.settings.i18n_default_locale = "de"
    res = await call(app, "GET", s.token)
    assert '<html lang="de">' in res.text
    assert "Abmelden</button>" in res.text
    assert "Klicken Sie" in res.text
    assert res.headers["content-language"] == "de"


async def test_get_does_no_database_work(world):
    app, _, _, s = world

    def explode():
        raise AssertionError("GET opened a session")

    app.state.sm.db.session_factory = explode
    assert (await call(app, "GET", s.token)).status_code == 200


async def test_markup_is_escaped():
    from sm_newsletter.web.endpoints.unsubscribe_page import render_page

    copy = {"title": "<t>", "intro": "a&b", "button": '"x"', "done": "<d>"}
    page = render_page(copy=copy, locale='en"><script>', done=False)
    assert "<t>" not in page and "&lt;t&gt;" in page
    assert "a&amp;b" in page and "&quot;x&quot;" in page
    assert "<script>" not in page


async def test_no_host_secret_changes_nothing(world):
    app, state, events, s = world
    page = (await call(app, "POST", "x.1.1.AAAA")).content
    app.state.sm.settings.secret_key = ""
    before = await snapshot(state, s)
    assert (await call(app, "POST", s.token, data=ONE_CLICK)).content == page
    assert await snapshot(state, s) == before
    assert events == []


async def test_open_and_click_tokens_cannot_unsubscribe(world):
    app, state, events, s = world
    secret = app.state.sm.settings.secret_key
    any_post_page = (
        await call(app, "POST", constants.TEST_UNSUBSCRIBE_TOKEN, data=ONE_CLICK)
    ).content
    for purpose in ("o", "c"):
        token = tokens.sign(
            secret, purpose=purpose, tenant_id=T, campaign_id=s.campaign_id, send_id=s.send_id
        )
        res = await call(app, "POST", token, data=ONE_CLICK)
        assert res.content == any_post_page
    assert await status_of(state, s) == "confirmed"
    assert await suppressions(state, T) == []
    assert (await counters(state, s))["unsubscribe_count"] == 0
    assert events == []
