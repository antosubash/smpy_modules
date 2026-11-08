from datetime import UTC, datetime, timedelta

import pytest
from sm_analytics.collection.retention import cleanup
from sm_analytics.models import AnalyticsEvent, AnalyticsProperty, AnalyticsSession
from sm_analytics.reporting.reports import report


@pytest.mark.asyncio
async def test_reports_filter_geography_and_keep_unknown(factory):
    now = datetime(2026, 11, 8, 12, tzinfo=UTC)
    async with factory() as db:
        prop = AnalyticsProperty(id="p", tenant_id="a", name="Site")
        db.add(prop)
        await db.flush()
        db.add(
            AnalyticsSession(
                id="s",
                property_id="p",
                tenant_id="a",
                visitor="visitor",
                started_at=now,
                last_seen=now,
            )
        )
        await db.flush()
        for n, country in enumerate(["AT", "AT", ""]):
            db.add(
                AnalyticsEvent(
                    tenant_id="a",
                    property_id="p",
                    session_id="s",
                    visitor="visitor",
                    event_id=str(n),
                    kind="pageview",
                    path="/p/home",
                    created_at=now,
                    country=country,
                    country_name="Austria" if country else "",
                )
            )
        db.add(
            AnalyticsEvent(
                tenant_id="other",
                property_id="p",
                session_id="s",
                visitor="other",
                event_id="other",
                kind="pageview",
                path="/secret",
                created_at=now,
                country="DE",
            )
        )
        await db.commit()
        result = await report(db, "a", prop, start=now.date(), end=now.date(), now=now)
        assert result["totals"] == {"pageviews": 3, "events": 0, "visitors": 1, "sessions": 1}
        assert result["breakdowns"]["country"] == [
            {"value": "AT", "label": "Austria", "count": 2},
            {"value": "", "label": "Unknown", "count": 1},
        ]
        result = await report(
            db, "a", prop, start=now.date(), end=now.date(), now=now, filters={"country": ""}
        )
        assert result["totals"]["pageviews"] == 1
        assert result["recent"]["visitors"] == 1


@pytest.mark.asyncio
async def test_retention_is_bounded_and_tenant_scoped(factory):
    now = datetime(2026, 11, 8, tzinfo=UTC)
    async with factory() as db:
        db.add(AnalyticsProperty(id="p", tenant_id="a", name="Site"))
        await db.flush()
        db.add(
            AnalyticsSession(
                id="s",
                property_id="p",
                tenant_id="a",
                visitor="v",
                started_at=now - timedelta(days=100),
                last_seen=now - timedelta(days=100),
            )
        )
        await db.flush()
        for n in range(3):
            db.add(
                AnalyticsEvent(
                    tenant_id="a",
                    property_id="p",
                    session_id="s",
                    visitor="v",
                    event_id=str(n),
                    kind="pageview",
                    path="/",
                    created_at=now - timedelta(days=100),
                )
            )
        await db.commit()
        assert await cleanup(db, "other", now=now, retention_days=90, batch_size=2) == 0
        assert await cleanup(db, "a", now=now, retention_days=90, batch_size=2) == 2
        await db.commit()
        assert await cleanup(db, "a", now=now, retention_days=90, batch_size=2) == 1
