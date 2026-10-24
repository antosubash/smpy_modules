"""``MeterRegistry`` — which meters exist, installed as ``app.state.billing_meters``.

Billing creates it in ``register_settings`` (construction), so it exists
before any module's ``on_startup``. A consumer registers there with plain
keyword arguments and no billing import::

    reg = getattr(app.state, "billing_meters", None)
    if reg is not None:
        reg.define(key="ai.requests", kind="counter", label_key="ai.meters.requests")

Every metering call names a registered meter of the right kind, or raises
``UnknownMeterError``. The plan editor suggests the registered keys.
"""

from __future__ import annotations

from collections.abc import Iterator

from sm_billing.contracts.metering import MeterDefinition, MeterKind, UnknownMeterError
from sm_billing.metering.validate import METER_MAX, TTL_MAX, check_text

UNITS = frozenset({"count", "bytes", "tokens", "ms"})


class MeterRegistry:
    def __init__(self) -> None:
        self._meters: dict[str, MeterDefinition] = {}

    def define(
        self,
        key: str,
        kind: str,
        unit: str = "count",
        label_key: str = "",
        hold_ttl_seconds: int | None = None,
    ) -> MeterDefinition:
        """Register ``key``. Defining it again identically is a no-op; any
        other redefinition (a different kind, unit, …) raises at boot."""
        check_text("key", key, METER_MAX)
        meter_kind = MeterKind(kind)
        if unit not in UNITS:
            raise ValueError(f"unit must be one of {sorted(UNITS)}")
        if hold_ttl_seconds is not None:
            if meter_kind is not MeterKind.GAUGE:
                raise ValueError("hold_ttl_seconds is for gauges only")
            if isinstance(hold_ttl_seconds, bool) or not 1 <= hold_ttl_seconds <= TTL_MAX:
                raise ValueError(f"hold_ttl_seconds must be 1-{TTL_MAX}")
        definition = MeterDefinition(key, meter_kind, unit, label_key, hold_ttl_seconds)
        existing = self._meters.get(key)
        if existing is not None and existing != definition:
            raise ValueError(f"meter {key!r} is already defined as {existing}")
        self._meters[key] = definition
        return definition

    def get(self, key: str) -> MeterDefinition | None:
        return self._meters.get(key)

    def require(self, key: str, kind: MeterKind) -> MeterDefinition:
        """The definition of ``key``, which must be a ``kind`` meter."""
        definition = self._meters.get(key)
        if definition is None:
            raise UnknownMeterError(f"meter {key!r} is not registered")
        if definition.kind is not kind:
            raise UnknownMeterError(f"meter {key!r} is a {definition.kind}, not a {kind}")
        return definition

    def keys(self) -> list[str]:
        return sorted(self._meters)

    def __iter__(self) -> Iterator[MeterDefinition]:
        return iter(self._meters[k] for k in self.keys())

    def __contains__(self, key: object) -> bool:
        return key in self._meters
