"""A public news page carries the catalogue of its address's content locale (#450).

The framework ships one catalogue with each page, chosen for the reader (cookie,
then ``Accept-Language``). On ``/de/news/`` the module's own strings stayed
English for a visitor whose browser asks for English, beside pagebuilder's German
chrome. This boots the real host (the stub apps in ``modules/news/tests`` carry
no i18n shared props) with content languages ``en`` and ``de``.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))

# What ``main.py`` imports before ``create_app``: records seals its registry in the first app.
import records_collections  # noqa: E402, F401

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
FEED = "news.public.feed"
SECRET = "news-public-locale-test-secret-key-0123456789"


def _run(args: list[str], url: str, **env: str) -> None:
    result = subprocess.run(
        args,
        cwd=REPO,
        env={**os.environ, "SM_DATABASE_URL": url, **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.fixture
def host_app(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'host.db'}"
    _run([sys.executable, "-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"], url)
    _run(
        [sys.executable, "scripts/set_setting.py", "pagebuilder", "content_locales", '["en","de"]'],
        url,
        SM_SECRET_KEY=SECRET,
    )
    monkeypatch.setenv("SM_DATABASE_URL", url)
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    monkeypatch.setenv("SM_I18N_SUPPORTED_LOCALES", '["en","de"]')
    sys.modules.pop("main", None)
    try:
        yield importlib.import_module("main").app
    finally:
        sys.modules.pop("main", None)


def _catalogues(app, monkeypatch) -> dict[str, dict]:
    async def setup_done(_app) -> bool:
        return True

    monkeypatch.setattr(app.state.sm.setup_registry, "is_setup_complete", setup_done)

    async def exercise() -> dict[str, dict]:
        out: dict[str, dict] = {}
        async with app.router.lifespan_context(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost"
        ) as http:
            for name, path, lang in (
                ("de", "/de/news/", "en"),
                ("en", "/news/", "de"),
            ):
                response = await http.get(path, headers={**INERTIA, "Accept-Language": lang})
                assert response.status_code == 200, response.text[:300]
                out[name] = response.json()["props"]["i18n"]
        return out

    return asyncio.run(exercise())


def test_a_page_speaks_the_language_of_its_address(host_app, monkeypatch):
    got = _catalogues(host_app, monkeypatch)
    locales = REPO / "modules" / "news" / "news" / "locales"
    de = json.loads((locales / "de.json").read_text(encoding="utf-8"))["public"]["feed"]
    en = json.loads((locales / "en.json").read_text(encoding="utf-8"))["public"]["feed"]

    # The German address ships the German catalogue to a browser asking for English...
    assert got["de"]["locale"] == "de"
    assert got["de"]["messages"][FEED] == de
    # ...and the default language's address stays English for a browser asking for German.
    assert got["en"]["locale"] == "en"
    assert got["en"]["messages"][FEED] == en
