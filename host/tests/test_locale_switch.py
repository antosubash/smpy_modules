"""The console's language switch works on the framework's own route.

Until framework 0.0.37 nothing served ``POST /i18n/set-locale``, so this host
carried its own copy (``host/locale_switch.py``). 0.0.37 mounts one in
``create_app`` (upstream #462) that writes the same ``i18n_cookie_name`` cookie
``LocaleMiddleware`` reads, and the shim is gone. These pin what the German
switch relies on, against the host's real ``main:app``: the route is served
exactly once, ``de`` sets the cookie and goes back where it came from, and it
never follows a Referer off-site.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))


@pytest.fixture
def host_app(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'host.db'}"
    env = {**os.environ, "SM_DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    monkeypatch.setenv("SM_DATABASE_URL", url)
    monkeypatch.setenv("SM_I18N_SUPPORTED_LOCALES", '["en","de"]')
    # An admin, so the first-run wizard is complete and SetupMiddleware does
    # not answer every request on this fresh database with a redirect to it.
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_EMAIL", "admin@example.com")
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_PASSWORD", "locale-switch-test-1")
    sys.modules.pop("main", None)
    try:
        yield importlib.import_module("main").app
    finally:
        sys.modules.pop("main", None)


def _post(app, locale: str, referer: str | None):
    async def run():
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = {"referer": referer} if referer else {}
                return await client.post(
                    "/i18n/set-locale", data={"locale": locale}, headers=headers
                )

    return asyncio.run(run())


def test_the_route_is_served_once_by_the_framework(host_app) -> None:
    routes = [r for r in iter_route_contexts(host_app.routes) if r.path == "/i18n/set-locale"]
    assert len(routes) == 1


def test_german_sets_the_cookie_and_goes_back(host_app) -> None:
    response = _post(host_app, "de", "http://test/pagebuilder/?tab=2")

    assert response.status_code == 303
    assert response.headers["location"] == "/pagebuilder/?tab=2"
    assert response.cookies["locale"] == "de"


def test_an_unsupported_locale_sets_nothing(host_app) -> None:
    response = _post(host_app, "fr", "http://test/ai/")

    assert "locale" not in response.cookies


@pytest.mark.parametrize(
    "referer",
    ["https://evil.example/x", "//evil.example/x", "/\\evil.example", None],
)
def test_it_never_redirects_off_site(host_app, referer: str | None) -> None:
    response = _post(host_app, "de", referer)

    assert response.headers["location"] == "/"
