"""A CSRF token from before a sign-in is refused after it, on the real host (#172).

Every module that uses the framework's ``RequiresCsrf`` (billing, news,
records) checks the token the session holds. Up to framework 0.0.38 a sign-in
kept the session, token included, so signing in without signing out first left
the earlier token valid. 0.0.42 replaces the session's state on sign-in
(upstream #615): this pins that, through news' admin API, with the real
``/api/users/auth/login`` — a module test runs on a bare app with stub auth and
never signs anyone in.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from simple_module_hosting.csrf import CSRF_HEADER

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))

ADMIN = ("admin@example.test", "Admin-pass-12345!")
VIEWER = ("viewer@example.test", "Viewer-pass-12345!")
ARTICLES = "/api/news/articles"


@pytest.fixture
def host(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'host.db'}"
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"],
        cwd=REPO,
        env={**os.environ, "SM_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    monkeypatch.setenv("SM_DATABASE_URL", url)
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_EMAIL", ADMIN[0])
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_PASSWORD", ADMIN[1])
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_USER_EMAIL", VIEWER[0])
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_USER_PASSWORD", VIEWER[1])
    monkeypatch.setenv("SM_RATE_LIMIT_PUBLIC", "100000/minute")
    sys.modules.pop("main", None)
    try:
        yield importlib.import_module("main").app
    finally:
        sys.modules.pop("main", None)


async def _sign_in(http: httpx.AsyncClient, who: tuple[str, str]) -> None:
    signed = await http.post("/api/users/auth/login", data={"username": who[0], "password": who[1]})
    assert signed.status_code in (200, 204), signed.text


async def _console_token(app, http: httpx.AsyncClient) -> str:
    """The token the news console is handed, as its own client reads it."""
    headers = {"X-Inertia": "true", "X-Inertia-Version": str(app.state.sm.inertia_config.version)}
    page = await http.get("/admin/news/", headers=headers)
    assert page.status_code == 200, page.text[:300]
    return page.json()["props"]["csrf_token"]


async def _create(http: httpx.AsyncClient, token: str, slug: str) -> httpx.Response:
    return await http.post(
        ARTICLES, json={"title": slug, "slug": slug}, headers={CSRF_HEADER: token}
    )


@pytest.mark.parametrize("second", [ADMIN, VIEWER], ids=["same-user", "other-user"])
async def test_a_token_from_before_a_sign_in_is_refused_after_it(host, second):
    async with host.router.lifespan_context(host):
        transport = httpx.ASGITransport(app=host)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            await _sign_in(http, ADMIN)
            before = await _console_token(host, http)
            assert (await _create(http, before, "before")).status_code == 201  # control

            await _sign_in(http, second)  # no sign-out in between

            stale = await _create(http, before, "stale")
            assert stale.status_code == 403, stale.text
            assert "CSRF" in stale.json()["detail"]

            if second is ADMIN:  # the new session's own token works
                after = await _console_token(host, http)
                assert after != before
                assert (await _create(http, after, "after")).status_code == 201
