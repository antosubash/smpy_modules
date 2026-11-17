"""Tests for CSP + Cache-Control + ETag on the public viewer (issues #6, #26)."""

from __future__ import annotations

from datetime import UTC, datetime

from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.web.public_cache import etag_for as _etag_for


def test_etag_is_stable_for_same_inputs() -> None:
    when = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    assert _etag_for(1, when) == _etag_for(1, when)


def test_etag_changes_when_updated_at_changes() -> None:
    a = _etag_for(1, datetime(2026, 5, 13, 12, 0, tzinfo=UTC))
    b = _etag_for(1, datetime(2026, 5, 13, 12, 1, tzinfo=UTC))
    assert a != b


def test_etag_changes_per_page() -> None:
    when = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    assert _etag_for(1, when) != _etag_for(2, when)


def test_etag_handles_missing_updated_at() -> None:
    # Newly-created pages have updated_at=None until first onupdate fire.
    assert _etag_for(1, None).startswith('W/"')


def test_default_csp_only_forbids_framing() -> None:
    """Beside the app's nonce policy the module's must restrict framing and nothing else."""
    assert PagebuilderSettings().public_csp == "frame-ancestors 'none'"


def test_cache_settings_have_safe_defaults() -> None:
    settings = PagebuilderSettings()
    assert settings.public_cache_max_age > 0
    assert settings.public_cache_swr >= 0
