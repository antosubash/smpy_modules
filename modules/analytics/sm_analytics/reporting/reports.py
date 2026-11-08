"""Bounded SQL aggregates; reporting never loads the event history into Python."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_analytics.models import AnalyticsEvent as E
from sm_analytics.models import AnalyticsProperty

DIMENSIONS = (
    "path",
    "referrer",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "browser",
    "os",
    "device",
    "country",
    "region",
    "city",
    "event",
)


def utc_day(dialect: str, column):
    return func.date(func.timezone("UTC", column) if dialect == "postgresql" else column)


async def report(
    db: AsyncSession,
    tenant: str,
    prop: AnalyticsProperty,
    *,
    start: date,
    end: date,
    now: datetime | None = None,
    filters: dict | None = None,
) -> dict:
    # shortcut: raw history scans; add daily rollups when long-range reports need low latency.
    now = now or datetime.now(UTC)
    begin = datetime.combine(start, datetime.min.time(), UTC)
    finish = datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)
    criteria = [
        E.tenant_id == tenant,
        E.property_id == prop.id,
        E.created_at >= begin,
        E.created_at < finish,
    ]
    for key, value in (filters or {}).items():
        if key in {"path", "event", "country", "region", "city"} and value is not None:
            criteria.append(getattr(E, "name" if key == "event" else key) == value)
    pageviews = func.coalesce(func.sum(case((E.kind == "pageview", 1), else_=0)), 0)
    events = func.coalesce(func.sum(case((E.kind == "event", 1), else_=0)), 0)
    row = (
        await db.execute(
            select(
                pageviews,
                events,
                func.count(func.distinct(E.visitor)),
                func.count(func.distinct(E.session_id)),
            ).where(*criteria)
        )
    ).one()
    totals = dict(zip(("pageviews", "events", "visitors", "sessions"), map(int, row), strict=True))
    day = utc_day(db.get_bind().dialect.name, E.created_at)
    daily = (
        await db.execute(
            select(day, pageviews, events).where(*criteria).group_by(day).order_by(day)
        )
    ).all()
    by_day = {str(d): {"pageviews": int(p), "events": int(e)} for d, p, e in daily}
    series = []
    current = start
    while current <= end:
        key = current.isoformat()
        series.append({"date": key, **by_day.get(key, {"pageviews": 0, "events": 0})})
        current += timedelta(days=1)
    breakdowns = {}
    for dimension in DIMENSIONS:
        col = getattr(E, "name" if dimension == "event" else dimension)
        extra = [E.kind == "event"] if dimension == "event" else []
        label = (
            getattr(E, f"{dimension}_name") if dimension in {"country", "region", "city"} else col
        )
        rows = (
            await db.execute(
                select(col, func.max(label), func.count())
                .where(*criteria, *extra)
                .group_by(col)
                .order_by(func.count().desc(), col)
                .limit(50)
            )
        ).all()
        breakdowns[dimension] = [
            {"value": v, "label": name or v or "Unknown", "count": n} for v, name, n in rows
        ]
    event_name = (filters or {}).get("event")
    for key in prop.event_allowlist.get(event_name, []):
        value = E.properties[key].as_string()
        rows = (
            await db.execute(
                select(value, func.count())
                .where(*criteria, E.kind == "event", value.is_not(None))
                .group_by(value)
                .order_by(func.count().desc())
                .limit(50)
            )
        ).all()
        breakdowns[f"property:{key}"] = [
            {"value": str(v), "label": str(v), "count": n} for v, n in rows
        ]
    recent_criteria = [*criteria, E.created_at >= now - timedelta(minutes=5)]
    active = await db.scalar(select(func.count(func.distinct(E.visitor))).where(*recent_criteria))
    recent = (
        await db.scalars(select(E).where(*recent_criteria).order_by(E.created_at.desc()).limit(50))
    ).all()
    return {
        "totals": totals,
        "series": series,
        "breakdowns": breakdowns,
        "recent": {
            "visitors": active,
            "events": [
                {
                    key: getattr(e, key)
                    for key in (
                        "event_id",
                        "kind",
                        "path",
                        "name",
                        "created_at",
                        "country",
                        "region",
                        "city",
                    )
                }
                for e in recent
            ],
        },
    }
