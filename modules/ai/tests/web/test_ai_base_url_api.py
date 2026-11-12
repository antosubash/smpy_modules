"""The base-URL guard and the probe contract over HTTP (#347)."""

from __future__ import annotations

import logging

import httpx2
import pytest
import pytest_asyncio
from sm_ai.connections import pinned
from sm_ai.core import constants, services
from sm_ai.web import probe_errors
from sm_ai.web.service import AiService

from tests.support.ai_api_app import api_client
from tests.support.ai_test_stubs import GrantAll, GrantSettingsEdit, fake_dns

SECRET = "test-secret-key-for-base-url-api"


@pytest_asyncio.fixture
async def manager(monkeypatch):
    async with api_client(monkeypatch, GrantAll, secret=SECRET, write_through=True) as http:
        yield http


@pytest_asyncio.fixture
async def admin(monkeypatch):
    async with api_client(
        monkeypatch, GrantSettingsEdit, secret=SECRET, write_through=True
    ) as http:
        yield http


PRIVATE = {"chat_provider": "openai_compatible", "chat_base_url": "http://ollama:11434/v1"}


class TestSave:
    async def test_the_switch_can_be_turned_off_over_a_saved_private_url(
        self, admin, monkeypatch
    ):
        # The stored private URL is not re-checked; it is refused at use instead.
        services.current_settings().allow_private_base_url = True
        services.current_settings().chat_provider = "openai_compatible"
        services.current_settings().chat_base_url = "http://ollama:11434/v1"
        fake_dns(monkeypatch, {"ollama": ["172.17.0.3"]})
        res = await admin.put(
            "/api/ai/settings",
            json={**PRIVATE, "allow_private_base_url": False},  # the page resends the URL
        )
        assert res.status_code == 200, res.text
        [applied] = admin.applied
        assert applied["allow_private_base_url"] is False
        body = (await admin.post("/api/ai/test", json={"slot": "chat"})).json()
        assert body["code"] == probe_errors.BASE_URL_REFUSED

    async def test_a_private_base_url_is_refused_naming_the_setting(self, manager, monkeypatch):
        fake_dns(monkeypatch, {"ollama": ["172.17.0.3"]})
        res = await manager.put("/api/ai/settings", json=PRIVATE)
        assert res.status_code == 422
        [error] = res.json()["detail"]
        assert error["loc"][-1] == "chat_base_url"
        assert "allow_private_base_url" in error["msg"]
        assert manager.applied == []

    async def test_the_switch_needs_settings_edit(self, manager):
        res = await manager.put("/api/ai/settings", json={"allow_private_base_url": True})
        assert res.status_code == 403
        assert constants.PERM_SETTINGS_EDIT in res.json()["detail"]
        assert manager.applied == []

    async def test_resending_the_current_value_needs_nothing(self, manager):
        # The page always sends the switch; an unchanged value is not a change.
        res = await manager.put(
            "/api/ai/settings", json={"allow_private_base_url": False, "chat_model": "x"}
        )
        assert res.status_code == 200

    async def test_a_late_save_cannot_restore_a_switch_an_admin_turned_off(
        self, manager, monkeypatch
    ):
        # Live true; an ai.manage save resends true unchanged; an admin turns it
        # off before that save persists. The late save must not write true back.
        services.current_settings().allow_private_base_url = True
        persisted = {"allow_private_base_url": True}

        async def _racing_apply(self, changes):
            persisted["allow_private_base_url"] = False  # the admin's save lands first
            persisted.update(changes)
            manager.applied.append(changes)
            return self.current()

        monkeypatch.setattr(AiService, "apply", _racing_apply)
        res = await manager.put(
            "/api/ai/settings", json={"allow_private_base_url": True, "chat_model": "x"}
        )
        assert res.status_code == 200
        assert manager.applied == [{"chat_model": "x"}]
        assert persisted["allow_private_base_url"] is False

    async def test_with_settings_edit_a_private_url_is_saved(self, admin, monkeypatch):
        asked = fake_dns(monkeypatch, {})
        res = await admin.put("/api/ai/settings", json={**PRIVATE, "allow_private_base_url": True})
        assert res.status_code == 200
        assert res.json()["allow_private_base_url"] is True
        assert asked == []


class TestProbe:
    async def test_a_refused_base_url_is_a_coded_result(self, manager, monkeypatch, caplog):
        fake_dns(monkeypatch, {"gw.example": ["10.0.0.7"]})
        services.current_settings().chat_provider = "openai_compatible"
        services.current_settings().chat_base_url = "http://gw.example/v1"
        with caplog.at_level(logging.WARNING, logger="sm_ai.web.probe_errors"):
            body = (await manager.post("/api/ai/test", json={"slot": "chat"})).json()
        assert body["ok"] is False
        assert body["code"] == probe_errors.BASE_URL_REFUSED
        assert body["error"] == probe_errors.MESSAGES[probe_errors.BASE_URL_REFUSED]
        assert all("sk-stored" not in r.getMessage() for r in caplog.records)

    async def test_the_provider_text_never_reaches_the_caller(self, manager, monkeypatch, caplog):
        def handler(request):
            return httpx2.Response(500, json={"error": {"message": "nginx on host-7.internal"}})

        monkeypatch.setattr(pinned, "_inner_transport", lambda: httpx2.MockTransport(handler))
        fake_dns(monkeypatch, {"gw.example": ["93.184.216.34"]})
        services.current_settings().chat_provider = "openai_compatible"
        services.current_settings().chat_base_url = "http://gw.example/v1"
        with caplog.at_level(logging.WARNING, logger="sm_ai.web.probe_errors"):
            res = await manager.post("/api/ai/models", json={"slot": "chat"})
        body = res.json()
        assert (body["code"], body["status"]) == (probe_errors.HTTP_ERROR, 500)
        assert "host-7" not in res.text
        assert any("host-7" in r.getMessage() for r in caplog.records)  # logged server-side


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (ConnectionRefusedError(111, "Connection refused"), probe_errors.CONNECTION_REFUSED),
        (TimeoutError(), probe_errors.TIMEOUT),
        (RuntimeError("boom"), probe_errors.OTHER),
    ],
)
def test_classify_reads_the_chain(exc, code):
    try:
        try:
            raise exc
        except BaseException as inner:
            raise ValueError("wrapped") from inner
    except ValueError as outer:
        assert probe_errors.classify(outer).code == code


def test_every_code_has_a_message():
    assert set(probe_errors.CODES) == set(probe_errors.MESSAGES)


class TestUnchangedUrls:
    async def test_a_save_that_leaves_a_stored_private_url_alone_is_not_refused(
        self, manager, monkeypatch
    ):
        # A URL stored before the guard existed: an unrelated save (the page
        # resends it unchanged) neither fails on it nor resolves its host.
        settings = services.current_settings()
        settings.chat_provider = "openai_compatible"
        settings.chat_base_url = "http://ollama:11434/v1"
        asked = fake_dns(monkeypatch, {"ollama": ["172.17.0.3"]})
        res = await manager.put(
            "/api/ai/settings",
            json={"chat_base_url": "http://ollama:11434/v1", "chat_model": "other"},
        )
        assert res.status_code == 200
        assert asked == []


def test_an_unfollowed_redirect_is_an_http_error_with_its_status():
    from pydantic_ai.exceptions import ModelHTTPError

    exc = ModelHTTPError(status_code=302, model_name="m", body=None)
    assert probe_errors.classify(exc) == (probe_errors.HTTP_ERROR, 302)
