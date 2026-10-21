"""Switching provider follows the live setting — no restart (#85)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from api_helpers import arm_csrf
from sm_billing import constants as c
from sm_billing import live, startup
from sm_billing.providers.manual import ManualProvider
from sm_billing.providers.stripe import StripeProvider

SETTINGS = f"/api/settings/modules/{c.PACKAGE}"
CONNECTION = "/api/billing/admin/connection"
WHSEC = "whsec_live"


@pytest.fixture
async def admin(authenticated_client):
    await arm_csrf(authenticated_client, "/admin/billing/plans")
    return authenticated_client


@pytest.fixture
async def stop_loop(app):
    yield
    await startup.stop_reconcile(app)


def _services(app):
    return app.state.sm_billing


async def _set(admin, **changes) -> None:
    response = await admin.put(SETTINGS, json=changes)
    assert response.status_code == 200, response.text


async def _connect(admin, webhook_secret: str = WHSEC) -> None:
    response = await admin.put(
        CONNECTION, json={"stripe_secret_key": "sk_test_1", "stripe_webhook_secret": webhook_secret}
    )
    assert response.status_code == 200, response.text


def _signed(secret: str) -> tuple[bytes, dict[str, str]]:
    """A Stripe event nothing acts on, signed the way Stripe signs."""
    body = json.dumps(
        {"id": "evt_live", "object": "event", "type": "invoice.created", "data": {"object": {}}}
    ).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return body, {"stripe-signature": f"t={ts},v1={sig}"}


async def test_manual_to_stripe_to_manual_without_restart(app, admin):
    assert isinstance(_services(app).provider, ManualProvider)
    await _connect(admin)  # secrets alone do not switch: the choice is still manual
    assert isinstance(_services(app).provider, ManualProvider)

    await _set(admin, provider=c.PROVIDER_STRIPE)
    assert isinstance(_services(app).provider, StripeProvider)
    billing = (await admin.get("/api/billing/admin/connection")).json()
    assert (billing["active_provider"], billing["provider_error"]) == ("stripe", "")

    await _set(admin, provider=c.PROVIDER_MANUAL)
    assert isinstance(_services(app).provider, ManualProvider)
    assert _services(app).provider_error == ""


async def test_switching_to_stripe_without_secrets_falls_back_and_says_why(app, admin):
    await _set(admin, provider=c.PROVIDER_STRIPE)
    assert isinstance(_services(app).provider, ManualProvider)
    assert "stripe_secret_key" in _services(app).provider_error
    await _connect(admin)  # the missing secrets arrive: stripe takes over at once
    assert isinstance(_services(app).provider, StripeProvider)
    assert _services(app).provider_error == ""


async def test_webhooks_follow_the_switch(app, admin, client):
    await _connect(admin)
    await _set(admin, provider=c.PROVIDER_STRIPE)
    body, headers = _signed(WHSEC)
    assert (await client.post(c.WEBHOOK_PATH, content=body, headers=headers)).status_code == 200

    # A rotated signing secret applies at once; the old one no longer verifies.
    await _connect(admin, webhook_secret="whsec_rotated")
    body, headers = _signed(WHSEC)
    stale = await client.post(c.WEBHOOK_PATH, content=body, headers=headers)
    assert stale.status_code == 400

    # Back on manual: Stripe deliveries are refused (404) and Stripe retries them.
    await _set(admin, provider=c.PROVIDER_MANUAL)
    body, headers = _signed("whsec_rotated")
    off = await client.post(c.WEBHOOK_PATH, content=body, headers=headers)
    assert (off.status_code, off.json()["detail"]) == (404, "stripe_not_configured")


async def test_reconcile_loop_follows_provider_and_interval(app, admin, stop_loop):
    await _set(admin, reconcile_interval_minutes=30)
    assert _services(app).scheduler is None  # manual: nothing to sync

    await _connect(admin)
    await _set(admin, provider=c.PROVIDER_STRIPE)
    loop = _services(app).scheduler
    assert loop.running and loop.interval.total_seconds() == 30 * 60

    await _connect(admin, webhook_secret="whsec_rotated")  # same interval: loop kept
    assert _services(app).scheduler is loop

    await _set(admin, reconcile_interval_minutes=60)
    retimed = _services(app).scheduler
    assert retimed is not loop and not loop.running
    assert retimed.running and retimed.interval.total_seconds() == 60 * 60

    await _set(admin, provider=c.PROVIDER_MANUAL)
    assert _services(app).scheduler is None and not retimed.running

    await _set(admin, provider=c.PROVIDER_STRIPE)
    assert _services(app).scheduler.running
    await _set(admin, reconcile_interval_minutes=0)
    assert _services(app).scheduler is None


async def test_other_packages_and_unrelated_fields_rebuild_nothing(app, admin):
    before = _services(app).provider
    await _set(admin, return_base_url="https://app.example.com")
    assert _services(app).provider is before
    await live.apply_reload(app, ["return_base_url"])
    assert _services(app).provider is before


async def test_reload_before_startup_is_a_no_op(app):
    _services(app).provider = None
    await live.apply_reload(app, ["provider"])
    assert _services(app).provider is None
