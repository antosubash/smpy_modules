"""HTTP helpers for the subscriptions API tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from httpx import ASGITransport, AsyncClient
from sm_events.feeds.subscriptions import launch
from sm_events.models import Subscription
from sqlalchemy import select

from tests.support.app import build_app
from tests.support.calendars import BASE, OWNER_P, make

REAL_LAUNCH = launch.refresh_one
SUBS = "/api/events/subscriptions"
URL = "https://feeds.example.test/private/SECRET-TOKEN-123/basic.ics?key=SECRET2"


@asynccontextmanager
async def app_client(**settings: Any) -> AsyncIterator[AsyncClient]:
    app, state = await build_app(settings=settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.app = app  # type: ignore[attr-defined]
        http.db_state = state  # type: ignore[attr-defined]
        yield http
    await state.engine.dispose()


async def calendar(client, headers=OWNER_P, **body) -> str:
    return (await make(client, headers, **body))["id"]


async def add(client, cid: str, headers: dict, url: str = URL, **body: Any):
    payload = {"url": url, "label": "Holidays", **body}
    return await client.post(f"{BASE}/{cid}/subscriptions", json=payload, headers=headers)


async def row(client, sid: str, *, include_deleted: bool = False) -> Subscription:
    async with client.db_state.session_factory() as db:
        stmt = select(Subscription).where(Subscription.id == uuid.UUID(sid))
        if include_deleted:
            stmt = stmt.execution_options(include_deleted=True)
        sub = (await db.execute(stmt)).scalar_one()
        db.expunge(sub)
        return sub


def stub_launch(monkeypatch) -> list[tuple[str, str]]:
    """Nothing is fetched (and no name is looked up) while a test saves a subscription."""
    started: list[tuple[str, str]] = []

    def record(db, *, tenant_id, subscription_id, **_):
        started.append((tenant_id, str(subscription_id)))

    monkeypatch.setattr(launch, "refresh_one", record)
    return started
