"""Records' newsletter contracts fetch their own settings from the caller's app (#336)."""

from __future__ import annotations

import sys

import pytest
from sm_records.contracts import newsletter, newsletter_import
from sm_records.contracts._newsletter_settings import records_settings
from sm_records.core.settings import RecordsSettings

from tests.support.contract_app import contract_app


def test_an_app_gives_its_hydrated_settings():
    settings = RecordsSettings()
    assert records_settings(contract_app(settings)) is settings


def test_no_app_is_a_worker_and_reads_settings_for(monkeypatch):
    background_tasks = pytest.importorskip("background_tasks")
    sentinel = RecordsSettings()
    seen: list[tuple[object, str]] = []

    def settings_for(cls, package):
        seen.append((cls, package))
        return sentinel

    monkeypatch.setattr(background_tasks, "settings_for", settings_for)
    assert records_settings(None) is sentinel
    assert seen == [(RecordsSettings, newsletter_import.RECORDS_PACKAGE)]


def test_no_app_without_background_tasks_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "background_tasks", None)
    with pytest.raises(RuntimeError, match="pass the app"):
        records_settings(None)


@pytest.mark.parametrize(
    "fn",
    [
        newsletter.unsubscribe,
        newsletter.set_tags,
        newsletter_import.create_list,
        newsletter_import.add_tag_choices,
        newsletter_import.import_subscribers,
    ],
)
def test_the_writes_take_an_app_not_settings(fn):
    import inspect

    params = inspect.signature(fn).parameters
    assert "settings" not in params
    assert params["app"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["app"].default is inspect.Parameter.empty, "a web caller must not forget it"


def test_records_settings_is_no_longer_exported():
    assert "RecordsSettings" not in newsletter_import.__all__
