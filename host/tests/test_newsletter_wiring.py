"""The host mounts newsletter and its tables reach the migration metadata."""

from __future__ import annotations

from simple_module_db import build_module_metadata
from simple_module_hosting import Settings, create_app

NEWSLETTER_TABLES = {
    "newsletter_campaign",
    "newsletter_segment",
    "newsletter_send",
    "newsletter_send_attempt",
    "newsletter_link",
    "newsletter_click",
    "newsletter_suppression",
    "newsletter_dispatch_lock",
}


def test_host_metadata_has_newsletter_tables():
    tables = set(build_module_metadata().tables)
    assert {t for t in tables if t.startswith("newsletter_")} == NEWSLETTER_TABLES


def test_host_loads_the_module():
    app = create_app(Settings())
    names = {m.meta.name for m in app.state.sm.modules}
    assert "Newsletter" in names
