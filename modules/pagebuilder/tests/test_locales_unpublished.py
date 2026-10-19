"""``pagebuilder.locales`` asked before anything was published (#129).

The fallback used to be stored in ``_active`` for the life of the process, so
one early call — a script, a worker, a neighbour's startup hook running first —
made the pydantic defaults look like published settings, silently and with
nothing logged. These pin that the fallback is never kept as the published
instance, and that reading it is loud. The module is reset around every test
by the fixture below: the shared ``locale_fixture`` plugin is only registered
when pagebuilder's tests are the run's rootdir config, so a combined run with
news' tests would otherwise leak ``_warned`` between tests.
"""

from __future__ import annotations

import logging

import pytest
from pagebuilder import locales
from pagebuilder.settings import PagebuilderSettings

_LOGGER = "simple_module.pagebuilder"


@pytest.fixture(autouse=True)
def _reset_locales():
    locales.reset()
    yield
    locales.reset()


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


def test_the_fallback_is_not_rebuilt_per_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building settings scans ``os.environ``; news' sitemap reads the
    locales per article, so the unpublished fallback has to be cheap."""
    locales._defaults()  # built at most once per process
    built = []
    real_init = PagebuilderSettings.__init__

    def counting_init(self, *args, **kwargs):
        built.append(1)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(PagebuilderSettings, "__init__", counting_init)
    for _ in range(100):
        locales.supported()
        locales.default()

    assert built == []
    assert locales._active is None


def test_startup_supersedes_the_pre_hydration_publish() -> None:
    """``register_settings`` publishes the defaults for pre-boot writers; the
    hydrated instance the host puts on ``app.state`` must replace them before
    anything is served — ``_live_settings`` runs first in ``on_startup``."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from pagebuilder.module import PagebuilderModule
    from settings.module_registry import ModuleSettingsRegistry

    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module = PagebuilderModule()
    module.register_settings(app)
    assert locales.supported() == PagebuilderSettings().content_locales

    app.state.pagebuilder.settings = PagebuilderSettings(
        content_locales=("en", "de"), default_content_locale="en"
    )
    module._live_settings(app)

    assert locales.supported() == ("en", "de")
