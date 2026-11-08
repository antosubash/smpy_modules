from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sm_analytics.collection.privacy import canonical_path, visitor_key
from sm_analytics.web.schemas import CollectIn, PropertyIn


def test_property_validates_origins_and_patterns():
    with pytest.raises(ValidationError):
        PropertyIn(name="Site", origins=["https://example.com/path"])
    with pytest.raises(ValidationError):
        PropertyIn(name="Site", origins=["https://example.com"], route_patterns=["/.*"])
    prop = PropertyIn(name="Site", origins=["https://EXAMPLE.com/"])
    assert prop.origins == ["https://example.com"]
    assert prop.enabled is False
    assert prop.route_patterns == []


def test_paths_strip_queries_and_normalize_application_identifiers():
    assert (
        canonical_path("/records/123?token=secret#part", ["/records/:id"], "application")
        == "/records/:id"
    )
    assert canonical_path("/de/p/about?email=secret", ["/de/p/:slug"], "public") == "/de/p/about"
    assert canonical_path("/records/123", [], "application") is None
    assert canonical_path("/settings/users", ["/settings/:id"], "application") is None
    assert canonical_path("//evil.example/path", ["/:id/:other"], "public") is None
    assert canonical_path("/%73ettings/users", ["/:first/:last"], "application") is None


def test_daily_visitor_keys_are_scoped_and_never_contain_ip():
    now = datetime(2026, 11, 8, tzinfo=UTC)
    args = ("secret", "tenant", "property", "192.0.2.1", "Firefox")
    key = visitor_key(*args, now)
    assert len(key) == 64 and "192.0.2.1" not in key
    assert key == visitor_key(*args, now + timedelta(hours=2))
    assert key != visitor_key(*args, now + timedelta(days=1))
    assert key != visitor_key("secret", "other", *args[2:], now)


def test_collector_rejects_nested_and_unbounded_event_values():
    base = {
        "property_id": "p",
        "event_id": "f040a315-7057-41aa-bb33-311aab4dcc02",
        "kind": "event",
        "path": "/",
        "name": "click",
    }
    with pytest.raises(ValidationError):
        CollectIn(**base, properties={"nested": {"secret": "value"}})
    with pytest.raises(ValidationError):
        CollectIn(**base, properties={"text": "x" * 501})
