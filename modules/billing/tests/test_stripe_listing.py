"""``StripeProvider.live_subscription_ids``: which statuses, and every page."""

from __future__ import annotations

from typing import Any

import stripe
from sm_billing.constants import PROVIDER_CANCELABLE_STATUSES
from sm_billing.providers.stripe import StripeProvider


def _sub(sid: str, status: str) -> dict[str, Any]:
    return {"id": sid, "object": "subscription", "status": status}


class _Pages:
    """``client.v1.subscriptions`` serving a listing in pages, like Stripe."""

    def __init__(self, items: list[dict[str, Any]], size: int) -> None:
        self.items, self.size = items, size
        self.params: list[dict[str, Any]] = []

    async def list_async(self, params: dict[str, Any]) -> stripe.StripeObject:
        self.params.append(params)
        start = 0
        if "starting_after" in params:
            start = 1 + [s["id"] for s in self.items].index(params["starting_after"])
        page = self.items[start : start + self.size]
        listing = {"object": "list", "data": page, "has_more": start + self.size < len(self.items)}
        return stripe.StripeObject.construct_from(listing, "sk_test")


def _provider(pages: _Pages) -> StripeProvider:
    provider = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_test")
    provider._v1 = type("V1", (), {"subscriptions": pages})()
    return provider


MIXED = [
    _sub("sub_a", "active"),
    _sub("sub_b", "canceled"),
    _sub("sub_c", "past_due"),
    _sub("sub_d", "incomplete_expired"),
    _sub("sub_e", "paused"),
    _sub("sub_f", "incomplete"),
    _sub("sub_g", "trialing"),
    _sub("sub_h", "unpaid"),
]


async def test_checkout_default_does_not_block_on_incomplete_or_paused():
    pages = _Pages(MIXED, size=100)
    ids = await _provider(pages).live_subscription_ids("cus_1")
    assert ids == ["sub_a", "sub_c", "sub_g", "sub_h"]
    assert pages.params == [{"customer": "cus_1", "status": "all", "limit": 100}]


async def test_teardown_set_includes_everything_not_ended():
    pages = _Pages(MIXED, size=100)
    ids = await _provider(pages).live_subscription_ids("cus_1", PROVIDER_CANCELABLE_STATUSES)
    assert ids == ["sub_a", "sub_c", "sub_e", "sub_f", "sub_g", "sub_h"]


async def test_every_page_is_read():
    """A live subscription past the first page must not be missed."""
    items = [_sub(f"sub_old_{i}", "canceled") for i in range(3)] + [_sub("sub_live", "active")]
    pages = _Pages(items, size=2)
    assert await _provider(pages).live_subscription_ids("cus_1") == ["sub_live"]
    assert [p.get("starting_after") for p in pages.params] == [None, "sub_old_1"]


async def test_a_listing_flagged_has_more_but_empty_ends():
    class _Stuck(_Pages):
        async def list_async(self, params):
            self.params.append(params)
            listing = {"object": "list", "data": [], "has_more": True}
            return stripe.StripeObject.construct_from(listing, "sk_test")

    pages = _Stuck([], size=1)
    assert await _provider(pages).live_subscription_ids("cus_1") == []
    assert len(pages.params) == 1
