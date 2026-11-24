"""The public frame contract reads only the caller's tenant and content language."""

from types import SimpleNamespace

import pytest
from pagebuilder.content.layout_service import LayoutService
from pagebuilder.contracts import public
from pagebuilder.core import locales
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.models import Page, PageStatus
from simple_module_db import current_tenant_id, tenant_context

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


def request(settings=None, tenant=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pagebuilder=SimpleNamespace(settings=settings))),
        state=SimpleNamespace(tenant_id=tenant),
    )


async def test_layout_and_nav_are_tenant_and_locale_scoped(db):
    settings = PagebuilderSettings(content_locales=("en", "de"))
    locales.use(settings)
    try:
        for tenant in ("acme", "globex"):
            with tenant_context(tenant):
                await LayoutService(db).update(
                    header_data={"content": [{"type": "Heading", "props": {"text": tenant}}]}
                )
                for locale in ("en", "de"):
                    db.add(
                        Page(
                            title=f"{tenant}-{locale}",
                            slug="about",
                            locale=locale,
                            status=PageStatus.PUBLISHED,
                            show_in_header_nav=True,
                            show_in_footer=True,
                        )
                    )
                await db.commit()
        # A different ambient tenant must not influence the contract's reads.
        with tenant_context("globex"):
            props = await public.layout_props(
                request(settings, "acme"), db, locale="de", tenant_id="acme"
            )
            assert current_tenant_id.get() == "globex"
        assert props["layout_header"]["content"][0]["props"]["text"] == "acme"
        assert props["layout_footer"] is None
        link = {"label": "acme-de", "href": "/de/p/about"}
        assert props["site_nav"] == {"header": [link], "footer": [link]}
        assert props["copy"]["skip_to_content"] == "Zum Inhalt springen"
        # Contract reads never finalize the caller's transaction.
        assert db.in_transaction()
    finally:
        locales.reset()


@pytest.mark.parametrize("settings,tenant", [(None, "acme"), (PagebuilderSettings(), None)])
async def test_no_site_or_tenant_returns_no_props_without_queries(settings, tenant):
    assert (
        await public.layout_props(request(settings), object(), locale="en", tenant_id=tenant) == {}
    )


async def test_resolved_tenant_mismatch_is_refused_before_reading():
    with pytest.raises(public.TenantMismatchError):
        await public.layout_props(
            request(PagebuilderSettings(), "acme"), object(), locale="en", tenant_id="globex"
        )
