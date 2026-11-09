from datetime import UTC, datetime

from sm_analytics.models import AnalyticsEvent
from sm_analytics.reporting.reports import utc_day
from sqlalchemy import select
from sqlalchemy.dialects import postgresql


def test_postgres_day_expression_explicitly_uses_utc():
    statement = select(utc_day("postgresql", AnalyticsEvent.created_at))
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "date(timezone('UTC', analytics_event.created_at))" in sql


async def test_postgres_non_utc_session_keeps_daily_totals_in_utc(factory):
    import pytest
    from sm_analytics.models import AnalyticsProperty, AnalyticsSession
    from sm_analytics.reporting.reports import report
    from sqlalchemy import text

    async with factory() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("Postgres timezone regression; use SM_TEST_DATABASE_URL")
        await db.execute(text("SET TIME ZONE 'America/Los_Angeles'"))
        now = datetime(2026, 11, 8, 0, 30, tzinfo=UTC)
        prop = AnalyticsProperty(id="p", tenant_id="a", name="Site")
        db.add(prop)
        await db.flush()
        db.add(
            AnalyticsSession(
                id="s", tenant_id="a", property_id="p", visitor="v", started_at=now, last_seen=now
            )
        )
        await db.flush()
        db.add(
            AnalyticsEvent(
                tenant_id="a",
                property_id="p",
                session_id="s",
                visitor="v",
                event_id="event",
                kind="pageview",
                path="/",
                created_at=now,
            )
        )
        await db.flush()
        result = await report(db, "a", prop, start=now.date(), end=now.date(), now=now)
        assert result["series"] == [{"date": "2026-11-08", "pageviews": 1, "events": 0}]
        assert result["totals"]["pageviews"] == 1
