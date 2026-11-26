"""A leftover ``SM_PAGEBUILDER_*`` variable is named at boot (#459)."""

from __future__ import annotations

import logging

import pytest
from pagebuilder.core import dead_env

LOGGER = "simple_module.pagebuilder"


def test_no_variable_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert dead_env.warn_on_dead_env({"SM_SECRET_KEY": "x", "SM_PAGEBUILDERX": "y"}) == []
    assert caplog.records == []


def test_a_known_setting_is_named_with_the_way_to_set_it(caplog):
    env = {"SM_PAGEBUILDER_MEDIA_ROOT": "/data/secret-path"}
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert dead_env.warn_on_dead_env(env) == ["SM_PAGEBUILDER_MEDIA_ROOT"]
    (record,) = caplog.records
    text = record.getMessage()
    assert "SM_PAGEBUILDER_MEDIA_ROOT is ignored" in text
    assert "set_setting.py pagebuilder media_root <value>" in text
    # The value may be a secret or a private path: it is never logged.
    assert "/data/secret-path" not in text


def test_an_unknown_name_is_reported_as_matching_nothing(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        dead_env.warn_on_dead_env({"SM_PAGEBUILDER_NO_SUCH_FIELD": "1"})
    assert "matches no pagebuilder setting" in caplog.records[0].getMessage()


def test_one_warning_per_variable_in_name_order_and_any_case(caplog):
    env = {"SM_PAGEBUILDER_REQUIRES_AUTH": "0", "sm_pagebuilder_content_locales": "[]"}
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        names = dead_env.warn_on_dead_env(env)
    assert names == ["SM_PAGEBUILDER_REQUIRES_AUTH", "sm_pagebuilder_content_locales"]
    assert [dead_env.dead_env_vars(env)[i][1] for i in (0, 1)] == [
        "requires_auth",
        "content_locales",
    ]
    assert len(caplog.records) == 2


def test_the_process_environment_is_the_default(monkeypatch, caplog):
    monkeypatch.setenv("SM_PAGEBUILDER_SITEMAP_ENABLED", "false")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert "SM_PAGEBUILDER_SITEMAP_ENABLED" in dead_env.warn_on_dead_env()


@pytest.mark.parametrize(
    ("env", "hinted"), [({"SM_PAGEBUILDER_MEDIA_ROOT": "/d"}, True), ({}, False)]
)
def test_the_media_hint_only_speaks_when_the_variable_is_set(caplog, env, hinted):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        dead_env.media_root_hint(env)
    assert bool(caplog.records) is hinted
    if hinted:
        assert "set_setting.py pagebuilder media_root" in caplog.records[0].getMessage()


async def test_startup_warns_about_a_leftover_variable(monkeypatch, tmp_path, caplog):
    from tests.support.app import _build_app

    monkeypatch.setenv("SM_PAGEBUILDER_PUBLIC_ROUTE_PREFIX", "/pages")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        _app, cleanup = await _build_app(
            tmp_path, requires_auth=False, csrf_protect=False, inject_user=False
        )
    await cleanup()
    assert any(
        "SM_PAGEBUILDER_PUBLIC_ROUTE_PREFIX is ignored" in r.getMessage() for r in caplog.records
    )


async def test_missing_media_names_the_ignored_media_root_variable(monkeypatch, tmp_path, caplog):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from pagebuilder.core import boot
    from pagebuilder.core.settings import PagebuilderSettings

    async def three_missing(_factory, _root):
        return 3

    monkeypatch.setenv("SM_PAGEBUILDER_MEDIA_ROOT", "/elsewhere")
    monkeypatch.setattr(boot, "warn_on_orphaned_media", three_missing)
    app = FastAPI()
    app.state.sm = SimpleNamespace(db=SimpleNamespace(session_factory=None))
    settings = PagebuilderSettings(
        media_root=str(tmp_path / "media"), snapshot_root=str(tmp_path / "snapshots")
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await boot.mount_media(app, settings)
    messages = [r.getMessage() for r in caplog.records]
    assert any("SM_PAGEBUILDER_MEDIA_ROOT is set but ignored" in m for m in messages)
