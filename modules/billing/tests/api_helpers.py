"""HTTP helpers: an owner with an active tenant and a CSRF token."""

from __future__ import annotations

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


async def create_tenant(client: httpx.AsyncClient, name: str = "Acme") -> dict:
    response = await client.post("/api/tenants/", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()
