"""``pagebuilder.locales`` asked before anything was published (#129).

The fallback used to be cached for the life of the process, so one early call —
a script, a worker, a neighbour's startup hook running first — pinned the
pydantic defaults and a later ``use()`` of the hydrated settings was ignored by
nothing but luck. These pin that the fallback is never kept, and that reading it
is loud. ``locale_fixture`` resets the module around every test.
"""

from __future__ import annotations

import logging

import pytest
from pagebuilder import locales
from pagebuilder.settings import PagebuilderSettings

_LOGGER = "simple_module.pagebuilder"


def test_a_later_use_takes_effect_after_an_early_call() -> None:
    assert locales.supported() == PagebuilderSettings().content_locales
    assert locales._active is None, "the fallback must not be cached"

    locales.use(
        PagebuilderSettings(content_locales=("de", "en"), default_content_locale="de")
    )

    assert locales.supported() == ("de", "en")
    assert locales.default() == "de"


def test_reading_before_use_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        locales.default()

    [record] = [r for r in caplog.records if r.name == _LOGGER]
    assert record.levelno == logging.WARNING
    assert "before use()" in record.getMessage()


def test_the_warning_is_logged_once_not_per_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """News borrows on every call where it was not published, so a host that
    never publishes would otherwise log on every request."""
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(3):
            locales.supported()

    assert len([r for r in caplog.records if r.name == _LOGGER]) == 1


def test_published_reads_do_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    locales.use(PagebuilderSettings())
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        locales.supported()

    assert not [r for r in caplog.records if r.name == _LOGGER]


def test_reset_rearms_the_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        locales.supported()
        locales.use(PagebuilderSettings())
        locales.reset()
        locales.supported()

    assert len([r for r in caplog.records if r.name == _LOGGER]) == 2


def test_news_borrow_follows_a_later_use() -> None:
    """News reads pagebuilder's locales through the seam when nothing was
    published to ``news.locales``; an early borrow must not pin the default."""
    news_locales = pytest.importorskip("news.locales")
    news_locales.reset()
    try:
        assert news_locales.supported() == PagebuilderSettings().content_locales
        locales.use(
            PagebuilderSettings(
                content_locales=("en", "fr"), default_content_locale="en"
            )
        )
        assert news_locales.supported() == ("en", "fr")
    finally:
        news_locales.reset()
