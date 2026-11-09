"""Selective filters and tenant-wide cleanup must have usable range prefixes."""

import pytest
from sm_analytics.models import Base
from sqlalchemy import create_engine


@pytest.mark.parametrize("dimension", ["country", "region", "city", "path", "name"])
def test_standalone_filter_uses_equality_then_time_range(dimension):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT count(*) FROM analytics_event "
            f"WHERE tenant_id=? AND property_id=? AND {dimension}=? "
            "AND created_at>=? AND created_at<?",
            ("tenant", "property", "value", "2026-01-01", "2026-01-08"),
        ).all()
    engine.dispose()
    plan = " ".join(row[3] for row in rows)
    assert f"{dimension}=? AND created_at>? AND created_at<?" in plan


@pytest.mark.parametrize(
    ("table", "timestamp"), [("analytics_event", "created_at"), ("analytics_session", "last_seen")]
)
def test_retention_uses_tenant_then_time_without_property(table, timestamp):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"EXPLAIN QUERY PLAN SELECT id FROM {table} "
            f"WHERE tenant_id=? AND {timestamp}<? LIMIT 5000",
            ("tenant", "2026-01-01"),
        ).all()
    engine.dispose()
    plan = " ".join(row[3] for row in rows)
    assert f"COVERING INDEX ix_{table}_retention (tenant_id=? AND {timestamp}<?)" in plan


@pytest.mark.parametrize("table", ["analytics_event", "analytics_session"])
def test_property_foreign_key_probe_uses_property_leading_search(table):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"EXPLAIN QUERY PLAN SELECT rowid FROM {table} WHERE property_id=?",
            ("deleted-property",),
        ).all()
    engine.dispose()
    plan = " ".join(row[3] for row in rows)
    assert "SEARCH" in plan and "(property_id=?)" in plan


@pytest.mark.parametrize(
    ("table", "predicate", "order", "prefix"),
    [
        (
            "analytics_event",
            "created_at>=? AND created_at<?",
            "created_at DESC",
            "property_id=? AND tenant_id=? AND created_at>? AND created_at<?",
        ),
        (
            "analytics_session",
            "visitor=? AND last_seen>?",
            "last_seen DESC",
            "property_id=? AND tenant_id=? AND visitor=? AND last_seen>?",
        ),
    ],
)
def test_property_leading_indexes_preserve_tenant_and_time_queries(table, predicate, order, prefix):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"EXPLAIN QUERY PLAN SELECT * FROM {table} "
            f"WHERE tenant_id=? AND property_id=? AND {predicate} ORDER BY {order} LIMIT 50",
            ("tenant", "property", "value", "2026-01-08"),
        ).all()
    engine.dispose()
    plan = " ".join(row[3] for row in rows)
    assert prefix in plan
    assert "TEMP B-TREE" not in plan
