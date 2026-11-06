"""``render_context``: the renderer's bases, branding and footer copy (R6, R7, R12)."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from simple_module_core.i18n import I18nRegistry
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.context import render_context, test_unsubscribe_url
from sm_newsletter.content.render import render
from sm_newsletter.content.render.types import RenderInput
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.core.tenancy import TenancyMode
from tenants.models import Tenant

from tests.pg_support import _pg

LOCALES = Path(str(importlib.resources.files("sm_newsletter") / "locales"))
SYS_LOGO = "6f1c2b9e-1111-4c8e-9a3f-000000000001"


def make_app(
    *,
    base="https://example.org/",
    locale="en",
    registry=None,
    branding=None,
    mode=TenancyMode.SINGLE,
    subdomain_base="",
    db=None,
    **settings,
) -> FastAPI:
    app = FastAPI()
    app.state.sm = SimpleNamespace(
        settings=SimpleNamespace(public_base_url=base, i18n_default_locale=locale),
        i18n_registry=registry or I18nRegistry("en", ["en"]),
        db=db,
    )
    app.state.sm_newsletter = SimpleNamespace(settings=NewsletterSettings(**settings), tenancy=mode)
    if branding is not None:
        app.state.branding = SimpleNamespace(settings=branding)
    if subdomain_base:
        app.state.tenants = SimpleNamespace(settings=SimpleNamespace(subdomain_base=subdomain_base))
    return app


def test_unsubscribe_url_shape():
    assert test_unsubscribe_url("https://example.org") == "https://example.org/newsletter/u/test"
    assert test_unsubscribe_url("") == "/newsletter/u/test"


async def test_branding_absent_defaults():
    c = await render_context(make_app(from_name="Club News"), tenant_id="default")
    assert (c.branding.app_name, c.branding.accent, c.branding.logo_url) == (
        "Club News",
        "#2563eb",
        "",
    )
    c = await render_context(make_app(), tenant_id="default")
    assert c.branding.app_name == "Newsletter"
    assert c.footer.reason == (
        "You are receiving this email because you subscribed to updates from Newsletter."
    )
    assert c.footer.unsubscribe == "Unsubscribe"


async def test_logo_url_absolute():
    branding = SimpleNamespace(app_name="Acme", primary_color="#0f766e", logo_file_id=SYS_LOGO)
    c = await render_context(make_app(branding=branding), tenant_id="default")
    assert c.branding.logo_url == f"https://example.org/newsletter/brand/logo?v={SYS_LOGO}"
    assert (c.branding.app_name, c.branding.accent) == ("Acme", "#0f766e")
    no_logo = SimpleNamespace(app_name="Acme", primary_color="", logo_file_id="")
    c = await render_context(make_app(branding=no_logo), tenant_id="default")
    assert (c.branding.logo_url, c.branding.accent) == ("", "#2563eb")


async def test_footer_copy_de():
    registry = I18nRegistry("de", ["en", "de"])
    registry.add_source("newsletter", LOCALES)
    registry.load()
    c = await render_context(
        make_app(locale="de", registry=registry, physical_address="Hauptstr. 1"),
        tenant_id="default",
    )
    assert c.locale == "de"
    assert c.footer.unsubscribe == "Abmelden"
    assert c.footer.reason.startswith("Sie erhalten diese E-Mail")
    assert "Newsletter" in c.footer.reason and "{app_name}" not in c.footer.reason
    assert c.physical_address == "Hauptstr. 1"


async def test_base_from_host_settings_not_request():
    c = await render_context(make_app(base="https://example.org/"), tenant_id="default")
    assert (c.content_base, c.public_base) == ("https://example.org", "https://example.org")
    c = await render_context(make_app(base=""), tenant_id="default")
    assert (c.content_base, c.public_base) == ("", "")


@pytest.fixture
async def tenants_db():
    state = await _pg.make_db_state(Tenant.metadata)
    async with state.session_factory() as s:
        s.add(Tenant(id="t1", slug="acme", name="Acme"))
        s.add(Tenant(id="t2", slug="bolt", name="Bolt"))
        await s.commit()
    yield state
    await state.engine.dispose()


async def test_tenants_get_their_own_content_origin(tenants_db):
    app = make_app(
        base="http://example.org:8000",
        mode=TenancyMode.MULTI,
        subdomain_base="example.org",
        db=tenants_db,
    )
    blocks = parse_body([{"type": "Button", "props": {"id": "b", "label": "Go", "href": "/p/x"}}])
    html = {}
    for tenant in ("t1", "t2"):
        c = await render_context(app, tenant_id=tenant)
        assert c.public_base == "http://example.org:8000"
        html[tenant] = render(RenderInput(subject="s", preheader="", blocks=blocks), c).html
    assert 'href="http://acme.example.org:8000/p/x"' in html["t1"]
    assert 'href="http://bolt.example.org:8000/p/x"' in html["t2"]
    # An unknown tenant, or no subdomain base, falls back to the host's own origin.
    assert (await render_context(app, tenant_id="nope")).content_base == "http://example.org:8000"
    single = make_app(base="https://example.org", mode=TenancyMode.MULTI, db=tenants_db)
    assert (await render_context(single, tenant_id="t1")).content_base == "https://example.org"


async def test_public_base_is_the_live_host_setting():
    """A ``host.public_base_url`` saved at runtime reloads ``app.state.host``, not the boot
    snapshot ``app.state.sm.settings``; the live value wins, a cleared one included."""
    app = make_app(base="https://boot.example.org")
    app.state.host = SimpleNamespace(
        settings=SimpleNamespace(public_base_url="https://live.example/")
    )
    c = await render_context(app, tenant_id="default")
    assert (c.public_base, c.content_base) == ("https://live.example", "https://live.example")
    app.state.host.settings.public_base_url = ""
    assert (await render_context(app, tenant_id="default")).public_base == ""
