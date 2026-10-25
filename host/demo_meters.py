"""Usage meters this demo host registers with billing — one of each kind.

No module in this repo meters anything yet (the first consumer, ai's
``ai.requests``, is a follow-up), so without these the tenant's usage card and
the admin Usage tab would have nothing to show in development or in the e2e
suite. ``scripts/seed_usage.py`` seeds usage against them for the e2e run.

Registered right after ``create_app``: billing creates the registry while the
app is built (``register_settings``), and a meter only has to exist before the
first metering call. A consumer module does the same from its own
``on_startup``. A host without billing has no registry, and this is a no-op.
"""

from __future__ import annotations

from typing import Any

#: ``{key, kind, unit, label_key}``, as ``MeterRegistry.define`` takes them.
DEMO_METERS: tuple[dict[str, Any], ...] = (
    {"key": "demo.exports", "kind": "counter", "unit": "count"},
    {"key": "demo.jobs", "kind": "gauge", "unit": "count"},
)


def register(app: Any) -> None:
    registry = getattr(app.state, "billing_meters", None)
    if registry is None:
        return
    for meter in DEMO_METERS:
        registry.define(**meter)
