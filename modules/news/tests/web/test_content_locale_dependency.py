"""The reader dependency resolves supported content locales before shared props."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from news.web.endpoints.public._lang import use_content_locale
from simple_module_core.i18n import I18nRegistry
from simple_module_hosting._inertia_shared import build_i18n_block
from simple_module_hosting.i18n_middleware import LocaleMiddleware
from simple_module_hosting.inertia_deps import InertiaDep


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "available", "reader", "expected"),
    [
        ("de", ["en", "de"], "en", "de"),
        ("en", ["en", "de"], "de", "en"),
        ("de-at", ["en", "de"], "en", "de"),
        ("DE-at", ["en", "de", "de-AT"], "en", "de-AT"),
        ("fr", ["en", "de"], "de", "de"),
        ("de", [], "en", "en"),
    ],
)
async def test_locale_resolution(content, available, reader, expected):
    app = FastAPI()
    app.state.sm = SimpleNamespace(
        i18n_registry=SimpleNamespace(available_locales=lambda: available)
    )
    request = Request({"type": "http", "app": app})
    request.state.locale = reader

    await use_content_locale(content)(request)

    assert request.state.locale == expected


@pytest.mark.asyncio
async def test_no_registry_keeps_the_reader_locale():
    request = Request({"type": "http", "app": FastAPI()})
    request.state.locale = "en"
    await use_content_locale("de")(request)
    assert request.state.locale == "en"


@pytest.mark.asyncio
async def test_router_dependency_precedes_lazy_inertia_on_success_error_and_redirect():
    app = FastAPI()
    registry = I18nRegistry(default_locale="en", supported_locales=["en", "de"])
    registry.add_source("news", Path(__file__).resolve().parents[2] / "news" / "locales")
    registry.load()
    app.state.sm = SimpleNamespace(i18n_registry=registry)

    class Shared:
        def share(self, **props):
            self.props = props

    app.state.inertia_dependency = lambda request, response: Shared()

    @app.middleware("http")
    async def lazy_shared(request, call_next):
        async def factory():
            return {"i18n": build_i18n_block(request.scope, request, is_authenticated=False)}

        request.state.inertia_shared_factory = factory
        return await call_next(request)

    app.add_middleware(LocaleMiddleware, supported_locales=["en", "de"], default_locale="en")
    router = APIRouter(dependencies=[Depends(use_content_locale("de"))])

    @router.get("/reader/{status}")
    async def reader(status: int, inertia: InertiaDep):
        # JSON snapshots are intentionally lazy; inspect the locale here.
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"locale": inertia.props["i18n"]["locale"]},
            status_code=status,
            headers={"Location": "/admin"} if status == 301 else None,
        )

    app.include_router(router)

    @app.get("/admin")
    async def admin(inertia: InertiaDep):
        return {"locale": inertia.props["i18n"]["locale"]}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.cookies.set("locale", "en")
        for status in (200, 404, 301):
            response = await http.get(f"/reader/{status}")
            assert response.status_code == status
            assert response.json()["locale"] == "de"
            assert "set-cookie" not in response.headers
        assert (await http.get("/admin")).json()["locale"] == "en"
        assert http.cookies.get("locale") == "en"
