"""Success pages borrow exactly the site's public layout, with the same cache boundaries."""

import pytest
from news.models import NewsCategory
from pagebuilder.models import Layout, Page, PageStatus
from simple_module_db import tenant_context

from tests.support.factories import make_article
from tests.support.site_app import FOOTER, HEADER, INERTIA, set_layout, site_client

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("locale,prefix", [("en", ""), ("de", "/de")])
async def test_article_and_all_archives_receive_the_frame(bilingual, locale, prefix):
    async for client in site_client(locales=bilingual):
        await set_layout(client)
        async with client.db_state.session_factory() as db:
            await make_article(db, slug="story", title="Story", locale=locale, author="Ada")
            db.add(NewsCategory(name="Field notes", slug="field-notes"))
            db.add(
                Page(
                    title="About",
                    slug="about",
                    locale=locale,
                    status=PageStatus.PUBLISHED,
                    show_in_header_nav=True,
                    show_in_footer=True,
                )
            )
            await db.commit()
        for path in (
            "/news/story",
            "/news/",
            "/news/?q=Story",
            "/news/tag/topic",
            "/news/author/ada",
            "/news/category/field-notes",
            "/news/category/field-notes?q=Story",
            "/news/tag/topic?q=Story",
            "/news/author/ada?q=Story",
        ):
            response = await client.get(prefix + path, headers=INERTIA)
            assert response.status_code == 200, response.text
            props = response.json()["props"]
            assert props["layout_header"] == HEADER
            assert props["layout_footer"] == FOOTER
            link = {"label": "About", "href": f"{prefix}/p/about"}
            assert props["site_nav"] == {"header": [link], "footer": [link]}
            assert props["copy"]["skip_to_content"] == (
                "Zum Inhalt springen" if locale == "de" else "Skip to content"
            )
            assert response.headers["Content-Language"] == locale
            assert "Content-Security-Policy" not in response.headers


@pytest.mark.parametrize("locale,prefix", [("en", ""), ("de", "/de")])
async def test_without_pagebuilder_the_pages_keep_their_plain_props(
    bilingual_public_client, monkeypatch, locale, prefix
):
    from news.integrations import pagebuilder

    monkeypatch.setattr(pagebuilder, "available", lambda: False)
    client = bilingual_public_client
    async with client.db_state.session_factory() as db:
        await make_article(db, slug="story", locale=locale)
    for path in ("/news/", "/news/story", "/news/?q=story"):
        response = await client.get(prefix + path, headers=INERTIA)
        assert response.status_code == 200
        props = response.json()["props"]
        assert not {"layout_header", "layout_footer", "site_nav", "copy"} & props.keys()


async def test_article_revalidation_changes_when_layout_or_nav_changes():
    async for client in site_client():
        await set_layout(client)
        async with client.db_state.session_factory() as db:
            await make_article(db, slug="story")
        first = await client.get("/news/story", headers={"Accept": "text/html"})
        etag = first.headers["ETag"]
        await set_layout(
            client, header={"content": [{"type": "Heading", "props": {"text": "New"}}]}
        )
        second = await client.get(
            "/news/story", headers={"Accept": "text/html", "If-None-Match": etag}
        )
        assert second.status_code == 200
        assert second.headers["ETag"] != etag
        async with client.db_state.session_factory() as db:
            db.add(
                Page(
                    title="About",
                    slug="about",
                    status=PageStatus.PUBLISHED,
                    show_in_header_nav=True,
                )
            )
            await db.commit()
        third = await client.get(
            "/news/story", headers={"Accept": "text/html", "If-None-Match": second.headers["ETag"]}
        )
        assert third.status_code == 200
        assert third.headers["ETag"] != second.headers["ETag"]


async def test_tenant_layouts_do_not_mix_and_keep_tenant_cache_variation():
    async for client in site_client(multi=True):
        for tenant in ("acme", "globex"):
            header = {"content": [{"type": "Heading", "props": {"text": tenant}}]}
            await set_layout(client, tenant, header=header)
            with tenant_context(tenant):
                async with client.db_state.session_factory() as db:
                    await make_article(db, slug="story", title=tenant)
        for tenant in ("acme", "globex"):
            for path in ("/news/", "/news/story"):
                response = await client.get(path, headers={**INERTIA, "x-tenant": tenant})
                assert response.status_code == 200
                props = response.json()["props"]
                assert props["layout_header"]["content"][0]["props"]["text"] == tenant
                assert "Cookie" in response.headers["Vary"]


@pytest.mark.parametrize("missing_model", [Layout, Page])
async def test_missing_optional_site_tables_do_not_break_news(bilingual, missing_model):
    async for client in site_client(locales=bilingual):
        if client.db_state.engine.dialect.name != "sqlite":
            pytest.skip("Missing-schema fixture uses an isolated SQLite database")
        async with client.db_state.session_factory() as db:
            for locale in bilingual:
                await make_article(db, slug="story", title="Story", locale=locale, author="Ada")
            db.add(NewsCategory(name="Field notes", slug="field-notes"))
            await db.commit()
        # Only this test's in-memory database is changed, never a host database.
        async with client.db_state.engine.begin() as connection:
            await connection.run_sync(missing_model.__table__.drop)
        for prefix in ("", "/de"):
            for path in (
                "/news/story",
                "/news/",
                "/news/?q=Story",
                "/news/category/field-notes",
                "/news/tag/topic",
                "/news/author/ada",
            ):
                response = await client.get(prefix + path, headers=INERTIA)
                assert response.status_code == 200, response.text
                props = response.json()["props"]
                assert not {"layout_header", "layout_footer", "site_nav", "copy"} & props.keys()


async def test_frame_recovery_invalidates_the_fallback_etag(monkeypatch):
    from pagebuilder.content.layout_service import LayoutService
    from sqlalchemy.exc import OperationalError

    async def unavailable(self):
        raise OperationalError("SELECT 1", {}, Exception("temporary failure"))

    async for client in site_client():
        await set_layout(client)
        async with client.db_state.session_factory() as db:
            await make_article(db, slug="story")
        with monkeypatch.context() as patch:
            patch.setattr(LayoutService, "get", unavailable)
            fallback = await client.get("/news/story", headers={"Accept": "text/html"})
        assert fallback.status_code == 200
        recovered = await client.get(
            "/news/story",
            headers={"Accept": "text/html", "If-None-Match": fallback.headers["ETag"]},
        )
        assert recovered.status_code == 200
        assert recovered.headers["ETag"] != fallback.headers["ETag"]
        assert "Site header" in recovered.text
