"""The published content locales and the path prefix each one adds."""

from __future__ import annotations

import pytest
from sm_events.core import locales


@pytest.fixture(autouse=True)
def _reset():
    locales.reset()
    yield
    locales.reset()


def test_fallback_is_english():
    assert locales.supported() == ("en",)
    assert locales.default() == "en"
    assert locales.path_prefix("en") == ""


def test_default_is_bare_and_others_are_prefixed():
    locales.use("en", "de")
    assert locales.supported() == ("en", "de")
    assert locales.is_default("en") and not locales.is_default("de")
    assert (locales.path_prefix("en"), locales.path_prefix("de")) == ("", "/de")


def test_default_is_the_first_and_duplicates_go():
    locales.use("de", "en", "de")
    assert locales.supported() == ("de", "en")
    assert locales.path_prefix("de") == ""


def test_empty_keeps_english():
    locales.use()
    assert locales.supported() == ("en",)
