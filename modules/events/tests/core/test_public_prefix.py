"""The public prefix: normalised, or refused with a fallback to ``/events``."""

from __future__ import annotations

import logging

import pytest
from sm_events.core.public_prefix import effective

VALID = [
    ("/events", "/events"),
    ("/events/", "/events"),
    ("events", "/events"),
    ("/what-s-on/de", "/what-s-on/de"),
    ("/whats-on", "/whats-on"),
]

INVALID = [
    "/",
    "",
    None,
    "/api/x",
    "/api",
    "/admin/events",
    "/users",
    "/static/x",
    "/Events",
    "/ev ents",
    "/ev..ts",
    "/a//b",
    "/events?x=1",
    "/events#x",
    "/é",
]


@pytest.mark.parametrize(("value", "expected"), VALID)
def test_valid(value, expected, caplog):
    with caplog.at_level(logging.ERROR, logger="sm_events.core.public_prefix"):
        assert effective(value) == expected
    assert not caplog.records


@pytest.mark.parametrize("value", INVALID)
def test_fallback(value, caplog):
    with caplog.at_level(logging.ERROR, logger="sm_events.core.public_prefix"):
        assert effective(value) == "/events"
    assert [r.levelno for r in caplog.records] == [logging.ERROR]
    assert "is not usable, serving at /events" in caplog.text


def test_taken_segment_is_refused(caplog):
    """Another mounted module's first path segment, or a content locale, is not ours."""
    with caplog.at_level(logging.ERROR, logger="sm_events.core.public_prefix"):
        assert effective("/news", taken=frozenset({"news"})) == "/events"
        assert effective("/de/events", taken=frozenset({"de"})) == "/events"
    assert len(caplog.records) == 2
    assert effective("/whats-on", taken=frozenset({"news"})) == "/whats-on"


def test_framework_prefixes_are_never_taken():
    from sm_events.core import constants

    for prefix in (constants.ROUTE_PREFIX_API, constants.VIEW_PREFIX):
        assert effective(prefix) == "/events"
