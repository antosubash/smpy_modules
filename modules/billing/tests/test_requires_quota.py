"""``RequiresQuota``: 402 body, refund only on a raised handler, key replays."""

from __future__ import annotations

import contextlib

import pytest
from quota_helpers import PREFIX, route
from sm_billing.metering.deps import RequiresQuota
from usage_helpers import METER, events


async def test_counts_then_answers_402(quota_app, owner):
    factory = quota_app.state.sm.db.session_factory
    assert (await owner.get(f"{PREFIX}/ok")).json() == {"used": 1, "replayed": False}
    assert (await owner.get(f"{PREFIX}/ok")).json()["used"] == 2
    refused = await owner.get(f"{PREFIX}/ok")
    assert refused.status_code == 402
    body = refused.json()
    assert body["detail"] == "quota_exceeded"
    assert {k: body[k] for k in ("meter", "limit", "used", "requested")} == {
        "meter": METER,
        "limit": 2,
        "used": 2,
        "requested": 1,
    }
    assert body["resets_at"].endswith("+00:00")
    assert await events(factory, owner.tenant_id) == 2


async def test_a_raised_handler_is_refunded(quota_app, owner):
    factory = quota_app.state.sm.db.session_factory
    assert (await owner.get(f"{PREFIX}/boom")).status_code == 418
    assert await events(factory, owner.tenant_id, kind="refund") == 1
    assert (await owner.get(f"{PREFIX}/ok")).json()["used"] == 1


async def test_a_returned_error_keeps_the_charge(quota_app, owner):
    assert (await owner.get(f"{PREFIX}/soft")).status_code == 422
    assert (await owner.get(f"{PREFIX}/ok")).json()["used"] == 2


async def test_a_replayed_key_never_reruns_the_handler(quota_app, owner, runs):
    headers = {"Idempotency-Key": "client-1"}
    first = await owner.get(f"{PREFIX}/count", headers=headers)
    again = await owner.get(f"{PREFIX}/count", headers=headers)
    assert first.json() == {"used": 1}
    assert again.status_code == 409 and again.json()["detail"] == "idempotency_replay"
    assert runs == [1]  # the handler ran once
    factory = quota_app.state.sm.db.session_factory
    assert await events(factory, owner.tenant_id) == 1  # and the replay was not charged
    # The same key on another route is another call: 409, never a free pass.
    other = await owner.get(f"{PREFIX}/soft", headers=headers)
    assert other.status_code == 409 and other.json()["detail"] == "idempotency_conflict"


async def test_a_refunded_key_is_spent_and_never_reruns(quota_app, owner, runs):
    """A key whose run raised was refunded; retrying it is refused, not re-run."""
    headers = {"Idempotency-Key": "client-2"}
    assert (await owner.get(f"{PREFIX}/count-boom", headers=headers)).status_code == 418
    retry = await owner.get(f"{PREFIX}/count-boom", headers=headers)
    assert retry.status_code == 409 and retry.json()["detail"] == "idempotency_key_spent"
    assert runs == [1]
    # A new key runs (and is charged) again.
    fresh = {"Idempotency-Key": "client-3"}
    assert (await owner.get(f"{PREFIX}/count-boom", headers=fresh)).status_code == 418
    assert runs == [1, 1]


@pytest.mark.parametrize("key", ["x" * 122, "a:refund", "adjust:1", " "])
async def test_bad_keys_are_400(quota_app, owner, key):
    response = await owner.get(f"{PREFIX}/ok", headers={"Idempotency-Key": key})
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_idempotency_key"


async def test_no_tenant_is_403(quota_app, user_client):
    async with user_client("lonely@x.io") as (client, _):
        response = await client.get(f"{PREFIX}/ok")
    assert response.status_code == 403
    assert response.json()["detail"] == "tenant_required"


async def test_without_billing_started_nothing_is_limited(quota_app, owner, monkeypatch):
    monkeypatch.delattr(quota_app.state, "billing_usage")

    async def free(outcome=RequiresQuota(METER)):
        return {"outcome": outcome}

    route(quota_app, "/free", free)
    assert (await owner.get(f"{PREFIX}/free")).json() == {"outcome": None}
    assert await events(quota_app.state.sm.db.session_factory, owner.tenant_id) == 0


def test_bad_arguments_fail_at_definition():
    with pytest.raises(ValueError):
        RequiresQuota(METER, 0)
    with pytest.raises(ValueError):
        RequiresQuota("")


async def _send_fails_on_body(app, client, path: str) -> list[str]:
    """Drive ``path`` straight through ASGI with a ``send`` that breaks on the
    body, as a client that disconnects mid-delivery does. Returns the message
    types that went out."""
    cookie = client.build_request("GET", path).headers["cookie"]  # what httpx would send
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"cookie", cookie.encode())],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    sent: list[str] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message["type"])
        if message["type"] == "http.response.body":
            raise OSError("client went away")

    with contextlib.suppress(OSError):
        await app(scope, receive, send)
    return sent


async def test_a_failed_delivery_after_success_is_not_refunded(quota_app, owner, runs):
    factory = quota_app.state.sm.db.session_factory
    sent = await _send_fails_on_body(quota_app, owner, f"{PREFIX}/count")
    assert runs == [1] and "http.response.start" in sent
    assert await events(factory, owner.tenant_id, kind="consume") == 1
    assert await events(factory, owner.tenant_id, kind="refund") == 0  # the work was done
    # A handler that raises is still refunded.
    assert (await owner.get(f"{PREFIX}/count-boom")).status_code == 418
    assert await events(factory, owner.tenant_id, kind="refund") == 1
