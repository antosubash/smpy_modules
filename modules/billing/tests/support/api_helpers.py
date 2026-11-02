"""HTTP helpers: an owner with an active tenant and a CSRF token."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
from simple_module_hosting.csrf import CSRF_HEADER

INERTIA = {"X-Inertia": "true"}


async def page_props(client: httpx.AsyncClient, url: str) -> dict:
    response = await client.get(url, headers=INERTIA)
    assert response.status_code == 200, response.text
    return response.json()["props"]


async def arm_csrf(client: httpx.AsyncClient, url: str = "/billing/") -> str:
    token = (await page_props(client, url))["csrf_token"]
    client.headers[CSRF_HEADER] = token
    return token


def signed_stripe_event(secret: str) -> tuple[bytes, dict[str, str]]:
    """A Stripe event nothing acts on, signed the way Stripe signs."""
    body = json.dumps(
        {"id": "evt_live", "object": "event", "type": "invoice.created", "data": {"object": {}}}
    ).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return body, {"stripe-signature": f"t={ts},v1={sig}"}


async def create_tenant(client: httpx.AsyncClient, name: str = "Acme") -> dict:
    response = await client.post("/api/tenants/", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()
