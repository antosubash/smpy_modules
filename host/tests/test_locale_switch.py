"""The language switcher's POST sets the locale cookie and goes back, safely."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from simple_module_hosting import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locale_switch import locale_switch_router

pytestmark = pytest.mark.asyncio


def _client() -> AsyncClient:
    app = FastAPI()
    app.include_router(locale_switch_router(Settings(i18n_supported_locales=["en", "de"])))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _switch(locale: str, referer: str | None = None):
    headers = {"referer": referer} if referer else {}
    async with _client() as client:
        return await client.post("/i18n/set-locale", data={"locale": locale}, headers=headers)


async def test_a_supported_locale_sets_the_cookie_and_goes_back() -> None:
    response = await _switch("de", "http://test/pagebuilder/?tab=2")

    assert response.status_code == 303
    assert response.headers["location"] == "/pagebuilder/?tab=2"
    assert response.cookies["locale"] == "de"


async def test_an_unsupported_locale_sets_nothing() -> None:
    response = await _switch("fr", "http://test/ai/")

    assert response.headers["location"] == "/ai/"
    assert "locale" not in response.cookies


@pytest.mark.parametrize(
    "referer", ["https://evil.example/x", "//evil.example/x", "javascript:alert(1)", None]
)
async def test_it_never_redirects_off_site(referer: str | None) -> None:
    response = await _switch("de", referer)

    assert response.headers["location"] == "/"
