from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sm_analytics.collection.service import collect
from sm_analytics.core.geo import GeoResolver
from sm_analytics.models import AnalyticsEvent, AnalyticsProperty, AnalyticsSession
from sm_analytics.web.schemas import CollectIn
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_collect_deduplicates_and_splits_inactive_daily_sessions(factory):
    now = datetime(2026, 11, 8, 10, tzinfo=UTC)
    async with factory() as db:
        prop = AnalyticsProperty(
            tenant_id="a",
            name="Site",
            origins=["https://example.com"],
            enabled=True,
            route_patterns=["/p/:slug"],
            event_allowlist={"signup": ["plan"]},
        )
        db.add(prop)
        await db.commit()

        def payload():
            return CollectIn(
                property_id=prop.id, event_id=uuid4(), kind="pageview", path="/p/about?token=secret"
            )

        first = payload()
        kwargs = {
            "tenant": "a",
            "ip": "127.0.0.1",
            "ua": "Firefox/123",
            "secret": "secret",
            "geo": GeoResolver(),
        }
        assert await collect(db, first, now=now, **kwargs)
        assert not await collect(db, first, now=now, **kwargs)
        assert await collect(db, payload(), now=now + timedelta(minutes=29), **kwargs)
        assert await collect(db, payload(), now=now + timedelta(minutes=60), **kwargs)
        assert await collect(db, payload(), now=now + timedelta(days=1), **kwargs)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(AnalyticsEvent)) == 4
        assert await db.scalar(select(func.count()).select_from(AnalyticsSession)) == 3
        event = (await db.scalars(select(AnalyticsEvent))).first()
        assert event.path == "/p/about"
        assert event.country == ""
        assert await collect(db, payload(), now=now, **(kwargs | {"tenant": "other"})) is False


@pytest.mark.asyncio
async def test_event_allowlist_and_pause_fail_closed(factory):
    async with factory() as db:
        prop = AnalyticsProperty(
            tenant_id="a",
            name="App",
            kind="application",
            enabled=True,
            origins=["https://example.com"],
            route_patterns=["/records/:id"],
            event_allowlist={"save": ["kind"]},
        )
        db.add(prop)
        await db.commit()
        data = CollectIn(
            property_id=prop.id,
            event_id=uuid4(),
            kind="event",
            path="/records/secret",
            name="save",
            properties={"kind": "note", "email": "private"},
        )
        kwargs = {
            "tenant": "a",
            "ip": "127.0.0.1",
            "ua": "",
            "secret": "secret",
            "geo": GeoResolver(),
            "now": datetime.now(UTC),
        }
        assert await collect(db, data, **kwargs)
        event = (await db.scalars(select(AnalyticsEvent))).one()
        assert event.path == "/records/:id" and event.properties == {"kind": "note"}
        prop.enabled = False
        await db.commit()
        assert not await collect(db, data.model_copy(update={"event_id": uuid4()}), **kwargs)
