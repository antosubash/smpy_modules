"""StripeProvider checkout: the session params and the ``client_reference_id`` round trip."""

from __future__ import annotations

from types import SimpleNamespace

from stripe_helpers import _Recorder


async def test_fetch_checkout_reads_the_retrieved_session(provider):
    session = {
        "id": "cs_1",
        "object": "checkout.session",
        "subscription": {"id": "sub_9", "object": "subscription"},
        "client_reference_id": "t9",
        "customer": "cus_9",
    }
    provider._v1.checkout = SimpleNamespace(sessions=_Recorder(provider.calls, "checkout", session))
    checkout = await provider.fetch_checkout("cs_1")
    assert provider.calls[-1][:2] == ("checkout.retrieve_async", ("cs_1",))
    assert (checkout.subscription_id, checkout.tenant_id, checkout.customer_id) == (
        "sub_9",
        "t9",
        "cus_9",
    )


async def test_checkout_params(provider):
    session = await provider.create_checkout(
        customer_id="cus_1",
        price_id="price_team_m",
        quantity=3,
        trial_days=14,
        tenant_id="t1",
        success_url="https://a/ok",
        cancel_url="https://a/no",
    )
    assert (session.id, session.url) == ("cs_1", "https://co/1")
    name, _, params = provider.calls[-1]
    assert name == "checkout.create_async"
    assert params["mode"] == "subscription"
    assert params["client_reference_id"] == "t1"
    assert params["line_items"] == [{"price": "price_team_m", "quantity": 3}]
    assert params["subscription_data"] == {"metadata": {"tenant_id": "t1"}, "trial_period_days": 14}


async def test_checkout_reference_of_a_user_subject_is_a_valid_stripe_reference(provider):
    subject = "user:0b8f6a52-5b0a-4c0e-9f43-2f5f9a3c7d10"
    await provider.create_checkout(
        customer_id=None,
        price_id="price_p",
        quantity=1,
        trial_days=0,
        tenant_id=subject,
        success_url="https://a/ok",
        cancel_url="https://a/no",
    )
    params = provider.calls[-1][2]
    assert ":" not in params["client_reference_id"]
    assert params["subscription_data"]["metadata"] == {"tenant_id": subject}
    ref = params["client_reference_id"]
    session = {"id": "cs_1", "subscription": "sub_9", "client_reference_id": ref, "customer": "c9"}
    provider._v1.checkout = SimpleNamespace(sessions=_Recorder(provider.calls, "checkout", session))
    assert (await provider.fetch_checkout("cs_1")).tenant_id == subject


async def test_checkout_without_trial_omits_trial(provider):
    await provider.create_checkout(
        customer_id="cus_1",
        price_id="p",
        quantity=1,
        trial_days=0,
        tenant_id="t1",
        success_url="s",
        cancel_url="c",
    )
    assert "trial_period_days" not in provider.calls[-1][2]["subscription_data"]


async def test_expire_checkout(provider):
    await provider.expire_checkout("cs_1")
    assert provider.calls[-1][:2] == ("checkout.expire_async", ("cs_1",))
