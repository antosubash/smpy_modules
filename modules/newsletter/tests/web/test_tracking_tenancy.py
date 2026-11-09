"""The tracking routes take the tenant from the verified token (S8), with distinct real ids (A9).

Tenants A and B each have a sent campaign with one link and one ``sent`` row,
and B's ids are never A's. A token pairing one tenant's ids with the other's,
or a host that resolved another tenant, writes nothing in either tenant. A
tenant the visitor brought (a signed-in member's session) does not count
against the link, as on the unsubscribe route.
"""

from __future__ import annotations

import pytest

from tests.support.tracking_http import (
    click_path,
    get,
    open_path,
    sign,
    snapshot,
    tracking_app,
)
from tests.support.tracking_world import sent_campaign

pytestmark = pytest.mark.unbound_tenant


async def _two(*, multi: bool = False):
    app, state = await tracking_app(multi=multi)
    a = await sent_campaign(state, "a")
    await sent_campaign(state, "b")  # a spare, so B's ids differ from A's
    b = await sent_campaign(state, "b")
    assert b[0] != a[0] and b[1][0] != a[1][0]
    return app, state, a, b


async def _both(state, a, b) -> tuple[dict, dict]:
    return (
        await snapshot(state, "a", a[0], a[1]),
        await snapshot(state, "b", b[0], b[1]),
    )


@pytest.fixture
async def two():
    app, state, a, b = await _two()
    yield app, state, a, b
    await state.engine.dispose()


@pytest.mark.parametrize("pairing", ["b_campaign_b_send", "a_campaign_b_send"])
async def test_signed_pairing_a_with_b_send_changes_nothing(two, pairing):
    app, state, a, b = two
    campaign = b[0] if pairing == "b_campaign_b_send" else a[0]
    before = await _both(state, a, b)
    res = await get(app, open_path(sign("o", "a", campaign, b[1][0])))
    assert res.status_code == 200
    res = await get(app, click_path(sign("c", "a", campaign, b[1][0])))
    # A's own campaign has a link 1, so the click still redirects; B's has none in A.
    assert res.status_code == (404 if pairing == "b_campaign_b_send" else 302)
    assert await _both(state, a, b) == before


@pytest.mark.parametrize("source", ["subdomain", "fixed"])
async def test_resolved_tenant_mismatch_changes_nothing(two, source):
    app, state, a, b = two
    headers = {"x-tenant": "b", "x-tenant-source": source}
    before = await _both(state, a, b)
    res = await get(app, open_path(sign("o", "a", a[0], a[1][0])), headers)
    assert res.status_code == 200
    res = await get(app, click_path(sign("c", "a", a[0], a[1][0])), headers)
    assert res.status_code == 404 and res.text == "Not found"
    assert await _both(state, a, b) == before


async def _counts_in_a_only(app, state, a, b, headers=None) -> None:
    before_b = await snapshot(state, "b", b[0], b[1])
    res = await get(app, open_path(sign("o", "a", a[0], a[1][0])), headers)
    assert res.status_code == 200
    res = await get(app, click_path(sign("c", "a", a[0], a[1][0])), headers)
    assert res.status_code == 302
    after_a = await snapshot(state, "a", a[0], a[1])
    assert after_a["counters"] == {
        "open_unique_count": 1,
        "open_total_count": 1,
        "click_unique_count": 1,
        "click_total_count": 1,
    }
    assert await snapshot(state, "b", b[0], b[1]) == before_b


@pytest.mark.parametrize("source", ["session", "header", "anon_header"])
async def test_a_visitor_derived_tenant_does_not_block_the_link(two, source):
    """A member of B signed in on the apex opens A's mail: it still counts in A."""
    app, state, a, b = two
    await _counts_in_a_only(app, state, a, b, {"x-tenant": "b", "x-tenant-source": source})


async def test_multi_tenant_apex_binds_the_tokens_tenant():
    app, state, a, b = await _two(multi=True)
    try:
        await _counts_in_a_only(app, state, a, b)
    finally:
        await state.engine.dispose()
