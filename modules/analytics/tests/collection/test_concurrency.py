import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from simple_module_db import tenant_context
from sm_analytics.collection.service import collect
from sm_analytics.core.geo import GeoResolver
from sm_analytics.models import AnalyticsEvent, AnalyticsProperty, AnalyticsSession
from sm_analytics.web.endpoints.admin import remove
from sm_analytics.web.schemas import CollectIn
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_concurrent_duplicate_is_one_event_and_one_session(factory):
    async with factory() as db:
        prop = AnalyticsProperty(
            id="p", tenant_id="a", name="Site", enabled=True, route_patterns=["/"]
        )
        db.add(prop)
        await db.commit()
    data = CollectIn(property_id="p", event_id=uuid4(), kind="pageview", path="/")

    async def send():
        async with factory() as db:
            result = await collect(
                db,
                data,
                tenant="a",
                ip="127.0.0.1",
                ua="",
                secret="key",
                geo=GeoResolver(),
                now=datetime.now(UTC),
            )
            await db.commit()
            return result

    assert sorted(await asyncio.gather(send(), send())) == [False, True]
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnalyticsEvent)) == 1
        assert await db.scalar(select(func.count()).select_from(AnalyticsSession)) == 1


@pytest.mark.asyncio
async def test_delete_waits_for_collector_then_removes_all_children(factory):
    async with factory() as db:
        db.add(
            AnalyticsProperty(
                id="p", tenant_id="a", name="Site", enabled=True, route_patterns=["/"]
            )
        )
        await db.commit()
    collected = asyncio.Event()
    allow_commit = asyncio.Event()

    async def send():
        async with factory() as db:
            await collect(
                db,
                CollectIn(property_id="p", event_id=uuid4(), kind="pageview", path="/"),
                tenant="a",
                ip="127.0.0.1",
                ua="",
                secret="key",
                geo=GeoResolver(),
                now=datetime.now(UTC),
            )
            collected.set()
            await allow_commit.wait()
            await db.commit()

    async def delete():
        await collected.wait()
        with tenant_context("a"):
            async with factory() as db:
                await remove("p", db)
                await db.commit()

    sender = asyncio.create_task(send())
    remover = asyncio.create_task(delete())
    await collected.wait()
    await asyncio.sleep(0.03)
    allow_commit.set()
    await asyncio.wait_for(asyncio.gather(sender, remover), 5)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnalyticsProperty)) == 0
        assert await db.scalar(select(func.count()).select_from(AnalyticsEvent)) == 0
        assert await db.scalar(select(func.count()).select_from(AnalyticsSession)) == 0
