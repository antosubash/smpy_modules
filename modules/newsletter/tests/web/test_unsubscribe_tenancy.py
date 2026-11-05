"""The unsubscribe route's tenant comes from the verified token (S8), with distinct real ids (A9).

Tenants A and B each have a list, a confirmed subscriber, a sent campaign and
a ``sent`` row, and B's ids are never A's. A token pairing one tenant's ids
with the other's, or a host that resolved another tenant, answers the same
page as a genuine click and changes nothing in either tenant.
"""

from __future__ import annotations

import pytest
from sm_newsletter.core import tokens

from tests.support.app import SECRET
from tests.support.unsub_world import (
    ONE_CLICK,
    Sent,
    app_with,
    call,
    sent_campaign,
    snapshot,
    status_of,
    suppressions,
)

pytestmark = pytest.mark.unbound_tenant


async def _two(*, multi: bool = False):
    app, state, events = await app_with(multi=multi)
    a = await sent_campaign(state, "a", "ada@example.org")
    # A spare campaign in B first, so B's campaign and send ids differ from A's.
    await sent_campaign(state, "b", "spare@example.org")
    b = await sent_campaign(state, "b", "bob@example.org", new_list=False)
    assert b.campaign_id != a.campaign_id and b.send_id != a.send_id
    return app, state, events, a, b


@pytest.fixture
async def two():
    app, state, events, a, b = await _two()
    yield app, state, events, a, b
    await state.engine.dispose()


async def _any_post_page(app) -> bytes:
    """What every POST answers (a forged token here): a genuine click gets the same page."""
    return (await call(app, "POST", "x.1.1.AAAA", data=ONE_CLICK)).content


async def _unchanged(app, state, events, a: Sent, b: Sent, token: str, **headers: str) -> None:
    before = await snapshot(state, a, b)
    res = await call(app, "POST", token, data=ONE_CLICK, headers=headers or None)
    assert res.status_code == 200
    assert res.content == await _any_post_page(app)
    assert await snapshot(state, a, b) == before
    assert events == []


async def test_signed_token_pairing_tenant_a_with_b_send_id_changes_nothing(two):
    """B's campaign and send ids, signed under tenant A: A has no such rows."""
    app, state, events, a, b = two
    token = tokens.sign(SECRET, tenant_id="a", campaign_id=b.campaign_id, send_id=b.send_id)
    await _unchanged(app, state, events, a, b, token)


async def test_signed_token_pairing_a_campaign_with_b_send_changes_nothing(two):
    """The tenant is A and the campaign A's; the send is B's. The
    ``(id, tenant_id, campaign_id)`` pin finds nothing."""
    app, state, events, a, b = two
    token = tokens.sign(SECRET, tenant_id="a", campaign_id=a.campaign_id, send_id=b.send_id)
    claims = tokens.parse(SECRET, token)
    assert claims is not None and claims.send_id == b.send_id
    await _unchanged(app, state, events, a, b, token)


async def test_same_tenant_second_campaign_with_first_campaigns_send_changes_nothing(two):
    """A valid MAC pairing tenant A's second campaign with its first campaign's
    send: the ``(id, tenant_id, campaign_id)`` pin finds nothing."""
    app, state, events, a, b = two
    second = await sent_campaign(state, "a", "eve@example.org", new_list=False)
    assert second.campaign_id != a.campaign_id
    token = tokens.sign(SECRET, tenant_id="a", campaign_id=second.campaign_id, send_id=a.send_id)
    before = await snapshot(state, second)
    await _unchanged(app, state, events, a, b, token)
    assert await snapshot(state, second) == before


async def test_resolved_host_tenant_mismatch_changes_nothing(two):
    app, state, events, a, b = two
    await _unchanged(app, state, events, a, b, a.token, **{"x-tenant": "b"})


async def test_multi_tenant_apex_binds_the_tokens_tenant():
    app, state, events, a, b = await _two(multi=True)
    try:
        before_b = await snapshot(state, b)
        res = await call(app, "POST", a.token, data=ONE_CLICK)
        assert res.status_code == 200
        assert res.content == await _any_post_page(app)
        assert await status_of(state, a) == "unsubscribed"
        assert await suppressions(state, "a") == [("unsubscribed", "news", "unsubscribe_page")]
        assert await snapshot(state, b) == before_b
        assert [(e.tenant_id, e.uuid) for e in events] == [("a", a.uuid)]
    finally:
        await state.engine.dispose()
