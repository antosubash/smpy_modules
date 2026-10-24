"""The meter registry: definitions, the kind check, plan-editor suggestions."""

from __future__ import annotations

import pytest
from api_helpers import page_props
from sm_billing.constants import METERS_STATE_ATTR, USAGE_STATE_ATTR
from sm_billing.contracts.metering import MeterKind, UnknownMeterError
from sm_billing.metering.registry import MeterRegistry
from usage_helpers import GAUGE, METER, gauge_service, seed_limits


def test_define_and_redefine():
    reg = MeterRegistry()
    first = reg.define(key=METER, kind="counter", label_key="ai.meters.requests")
    assert first.kind is MeterKind.COUNTER
    assert reg.define(key=METER, kind="counter", label_key="ai.meters.requests") == first
    with pytest.raises(ValueError, match="already defined"):
        reg.define(key=METER, kind="gauge")
    with pytest.raises(ValueError, match="already defined"):
        reg.define(key=METER, kind="counter", unit="tokens")
    assert reg.keys() == [METER] and METER in reg


@pytest.mark.parametrize(
    "kwargs",
    [
        {"key": "", "kind": "counter"},
        {"key": "x" * 65, "kind": "counter"},
        {"key": "k", "kind": "meter"},
        {"key": "k", "kind": "counter", "unit": "litres"},
        {"key": "k", "kind": "counter", "hold_ttl_seconds": 60},
        {"key": "k", "kind": "gauge", "hold_ttl_seconds": 0},
        {"key": "k", "kind": "gauge", "hold_ttl_seconds": 1.5},
    ],
)
def test_bad_definitions(kwargs):
    with pytest.raises(ValueError):
        MeterRegistry().define(**kwargs)


def test_require_checks_presence_and_kind():
    reg = MeterRegistry()
    reg.define(key=GAUGE, kind="gauge")
    assert reg.require(GAUGE, MeterKind.GAUGE).key == GAUGE
    with pytest.raises(UnknownMeterError, match="not registered"):
        reg.require(METER, MeterKind.COUNTER)
    with pytest.raises(UnknownMeterError, match="gauge, not a counter"):
        reg.require(GAUGE, MeterKind.COUNTER)


async def test_metering_an_unregistered_or_wrong_kind_meter_raises(app):
    factory = app.state.sm.db.session_factory
    usage = gauge_service(factory)
    tenant = await seed_limits(factory, {})
    with pytest.raises(UnknownMeterError):
        await usage.consume(tenant, "nope", 1, "k", source="t")
    with pytest.raises(UnknownMeterError):
        await usage.consume(tenant, GAUGE, 1, "k", source="t")
    with pytest.raises(UnknownMeterError):
        await usage.reserve(tenant, METER, 1, "k", source="t")
    with pytest.raises(UnknownMeterError):
        await usage.check(tenant, "nope")


def test_the_app_installs_the_registry_into_the_service(app):
    reg = getattr(app.state, METERS_STATE_ATTR)
    assert isinstance(reg, MeterRegistry)
    assert getattr(app.state, USAGE_STATE_ATTR)._meters is reg


async def test_the_plan_editor_suggests_registered_meters(app, authenticated_client):
    reg = getattr(app.state, METERS_STATE_ATTR)
    reg.define(key=METER, kind="counter")
    reg.define(key="tenants.seats", kind="gauge")  # already a known key: listed once
    props = await page_props(authenticated_client, "/admin/billing/plans")
    assert props["known_limit_keys"] == ["tenants.seats", METER]
