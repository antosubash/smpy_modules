"""``timezones``: which names are known and the UTC fallback."""

from __future__ import annotations

import logging

from sm_events.core import timezones


def test_is_known():
    assert timezones.is_known("Europe/Vienna")
    assert not timezones.is_known("Mars/Base")
    assert not timezones.is_known("")
    assert not timezones.is_known("europe/vienna")  # case matters


def test_effective_returns_a_known_name():
    assert timezones.effective("Europe/Vienna") == "Europe/Vienna"
    assert timezones.effective(None) == "UTC"


def test_effective_warns_once_per_unknown_name(caplog):
    timezones._warned.discard("Mars/Base")
    with caplog.at_level(logging.WARNING, logger="sm_events.core.timezones"):
        assert timezones.effective("Mars/Base") == "UTC"
        assert timezones.effective("Mars/Base") == "UTC"
    assert len([r for r in caplog.records if "Mars/Base" in r.getMessage()]) == 1
