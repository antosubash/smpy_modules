"""Console-only catalogues stay off anonymous pages (#417), without losing server copy."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from news.module import NewsModule
from pagebuilder.module import PagebuilderModule
from simple_module_core.menu import MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_hosting import Settings
from simple_module_hosting.i18n_manifest import build_i18n_registry
from simple_module_hosting.middleware import InertiaLayoutDataMiddleware
from sm_ai.module import AiModule
from sm_analytics.module import AnalyticsModule
from sm_billing.module import BillingModule
from sm_events.module import EventsModule
from sm_images.module import ImagesModule
from sm_newsletter.core.messages import server_copy
from sm_newsletter.module import NewsletterModule
from sm_newsletter.web.endpoints.unsubscribe_page import KEYS, render_page
from sm_records.module import RecordsModule
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    AiModule, AnalyticsModule, BillingModule, EventsModule, ImagesModule,
    NewsModule, NewsletterModule, PagebuilderModule, RecordsModule,
)
SWITCHED = ("ai", "analytics", "billing", "events", "newsletter")
PUBLIC = ("images", "news", "pagebuilder", "records")


@pytest.fixture(scope="module")
def catalogue_app():
    # No host startup, dotenv, database, generated files or background jobs.
    settings = Settings(_env_file=None, i18n_supported_locales=["en", "de"])
    modules = [cls() for cls in MODULES]
    registry, _ = build_i18n_registry(settings, modules, ROOT)
    app = FastAPI()
    app.state.sm = SimpleNamespace(i18n_registry=registry, settings=settings)
    return app, modules


def block(app, locale, user=None, *, session=None, cached=None):
    headers = [(b"x-inertia", b"true")]
    if cached is not None:
        headers.append((b"x-sm-i18n", cached.encode()))
    scope = {
        "type": "http", "method": "GET", "path": "/events/", "headers": headers,
        "app": app, "session": session if session is not None else {},
        "state": {"locale": locale, "user": user},
    }
    middleware = InertiaLayoutDataMiddleware(app, MenuRegistry(), PermissionRegistry())
    # Exercise the middleware's authentication decision too, after auth has
    # resolved the principal; no login or database fixture is needed here.
    shared = asyncio.run(middleware._shared(Request(scope), scope, user, set()))
    return shared["i18n"]


def namespace(messages, name):
    return {key: value for key, value in messages.items() if key.startswith(f"{name}.")}


def encoded_bytes(value):
    return len(json.dumps(value).encode("utf-8"))


@pytest.mark.parametrize("locale", ["en", "de"])
@pytest.mark.parametrize("name", SWITCHED)
def test_console_namespace_is_withheld_only_from_anonymous(catalogue_app, locale, name):
    app, modules = catalogue_app
    module = next(m for m in modules if name in m.locale_dirs())
    assert module.meta.i18n_audience == "admin"
    anonymous = block(app, locale)
    assert anonymous["audience"] == "public"
    assert namespace(anonymous["messages"], name) == {}
    for is_admin in (True, False):
        signed_in = block(app, locale, SimpleNamespace(is_superuser=is_admin))
        assert signed_in["audience"] == "full"
        assert namespace(signed_in["messages"], name)


@pytest.mark.parametrize("locale", ["en", "de"])
def test_public_dependencies_are_still_shipped(catalogue_app, locale):
    app, _ = catalogue_app
    messages = block(app, locale)["messages"]
    assert all(namespace(messages, name) for name in (*PUBLIC, "ui"))


@pytest.mark.parametrize("cached_header", [False, True])
def test_login_and_logout_replace_the_catalogue_at_the_same_locale(catalogue_app, cached_header):
    app, _ = catalogue_app
    session = {}
    block(app, "de", session=session)
    admin = SimpleNamespace(is_superuser=True)
    full = block(app, "de", admin, session=session, cached="de:public" if cached_header else None)
    assert namespace(full["messages"], "events")
    cached = block(app, "de", admin, session=session, cached="de:full" if cached_header else None)
    assert cached["messages"] is None
    public = block(app, "de", session=session, cached="de:full" if cached_header else None)
    assert not namespace(public["messages"], "events")


@pytest.mark.parametrize("locale,button", [("en", "Unsubscribe"), ("de", "Abmelden")])
def test_newsletter_unsubscribe_keeps_its_server_translations(catalogue_app, locale, button):
    app, _ = catalogue_app
    # server_copy follows the host default (the mail's language), not the request cookie.
    server = FastAPI()
    server.state.sm = SimpleNamespace(
        i18n_registry=app.state.sm.i18n_registry,
        settings=SimpleNamespace(i18n_default_locale=locale),
    )
    selected, copy = server_copy(server, "unsubscribe_page", KEYS)
    html = render_page(copy=copy, locale=selected, done=False)
    assert f'lang="{locale}"' in html
    assert f">{button}</button>" in html
    assert copy["done"] in render_page(copy=copy, locale=selected, done=True)
    assert not namespace(block(app, locale)["messages"], "newsletter")


def test_anonymous_catalogue_saving(catalogue_app):
    """Measure the real prop, using the initial HTML's JSON encoding (no gzip)."""
    app, _ = catalogue_app
    for locale in ("en", "de"):
        before = block(app, locale, SimpleNamespace(is_superuser=True))
        # Before #417 every repo module was public, so its anonymous messages
        # equalled today's full snapshot. Keep the audience field anonymous too.
        before["audience"] = "public"
        after = block(app, locale)
        saved = encoded_bytes(before["messages"]) - encoded_bytes(after["messages"])
        assert saved > 130_000
        print(
            f"{locale}: i18n {encoded_bytes(before):,} -> {encoded_bytes(after):,}; "
            f"saved {saved:,}"
        )
        for name in (*SWITCHED, *PUBLIC, "ui"):
            print(f"  {name}: {encoded_bytes(namespace(before['messages'], name)):,}")
